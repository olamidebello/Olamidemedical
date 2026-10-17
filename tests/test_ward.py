from datetime import datetime,timezone,timedelta
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parent))
import test_tenancy as fixtures
import server

class WardWorkflows(unittest.TestCase):
 setUp=fixtures.TenantIsolation.setUp
 tearDown=fixtures.TenantIsolation.tearDown
 req=fixtures.TenantIsolation.req
 login=fixtures.TenantIsolation.login
 create=fixtures.TenantIsolation.create
 patient=fixtures.TenantIsolation.patient
 def caregivers(self):
  server.add_user('nurseone',fixtures.PASSWORD,'nurse');server.add_user('nursetwo',fixtures.PASSWORD,'nurse');server.add_user('doctorone',fixtures.PASSWORD,'clinician')
  one=self.login('nurseone');two=self.login('nursetwo');doctor=self.login('doctorone')
  return (one,self.req('me',cookie=one)[1]['id']),(two,self.req('me',cookie=two)[1]['id']),(doctor,self.req('me',cookie=doctor)[1]['id'])
 def shift(self,uid,start,end):return self.create('duty-shifts',{'staff_id':uid,'department':'Ward A','shift_name':'Day','starts_at':start,'ends_at':end,'on_call':'primary'})
 def entry(self,p,cookie,kind='shift_assessment',fields=None,**extra):
  return self.create('clinical-entries',{'patient_id':p['id'],'entry_type':kind,'fields':fields or {'condition':'Synthetic stable observation'},'care_at':datetime.now(timezone.utc).isoformat(),**extra},cookie)
 def test_clinical_signatures_corrections_and_scope(self):
  (nurse,nid),(other,oid),(doctor,did)=self.caregivers();p=self.patient()
  entry=self.entry(p,nurse)
  self.assertEqual(self.req('clinical-entries',cookie=other)[1],[])
  self.assertEqual(self.req('clinical-entries','PATCH',{'id':entry['id'],'version':1,'action':'sign','confirm':True},other)[0],404)
  self.assertEqual(self.req('clinical-entries','PATCH',{'id':entry['id'],'version':1,'action':'sign','confirm':True},nurse)[0],200)
  signed=self.req('clinical-entries?patient_id='+str(p['id']),cookie=nurse)[1][0]
  self.assertEqual(signed['author_id'],nid);self.assertTrue(signed['signed_at'])
  self.assertEqual(self.req('clinical-entries','PATCH',{'id':entry['id'],'version':2,'action':'edit','fields':{'condition':'overwrite'}},nurse)[0],400)
  correction=self.entry(p,nurse,correction_of=entry['id'],correction_reason='Correct synthetic observation',fields={'condition':'Synthetic corrected observation'})
  self.assertTrue(correction['id']>entry['id'])
  self.assertEqual(self.req('clinical-entries',cookie=self.second)[1],[])
  self.assertEqual(self.req('clinical-entries','POST',{'patient_id':p['id'],'entry_type':'daily_progress','fields':{'assessment':'Wrong role'},'care_at':datetime.now(timezone.utc).isoformat()},nurse)[0],400)
  foreign=self.patient(self.second)
  self.assertEqual(self.req('clinical-entries','POST',{'patient_id':foreign['id'],'entry_type':'shift_assessment','fields':{'condition':'Foreign'},'care_at':datetime.now(timezone.utc).isoformat()},nurse)[0],400)
 def test_roster_overlaps_attendance_assignments_and_handover(self):
  (nurse,nid),(other,oid),_=self.caregivers();p=self.patient();now=datetime.now(timezone.utc)
  start=(now-timedelta(minutes=10)).isoformat();end=(now+timedelta(hours=7)).isoformat();shift=self.shift(nid,start,end)
  self.assertEqual(self.req('duty-shifts','POST',{'staff_id':nid,'department':'Ward B','shift_name':'Overlap','starts_at':start,'ends_at':end},self.first)[0],400)
  self.assertEqual(self.req('shift-patients','POST',{'shift_id':shift['id'],'patient_id':p['id']},self.first)[0],200)
  self.assertEqual(self.req('duty-shifts','PATCH',{'id':shift['id'],'version':1,'action':'clock-in'},other)[0],404)
  self.assertEqual(self.req('duty-shifts','PATCH',{'id':shift['id'],'version':1,'action':'clock-in'},nurse)[0],200)
  handover=self.entry(p,nurse,'nursing_handover',{'condition':'Synthetic handover','outstanding_tasks':'None'})
  self.req('clinical-entries','PATCH',{'id':handover['id'],'version':1,'action':'sign','confirm':True},nurse)
  self.assertEqual(self.req('duty-shifts','PATCH',{'id':shift['id'],'version':2,'action':'handover','entry_id':handover['id']},nurse)[0],200)
  self.assertEqual(self.req('duty-shifts',cookie=nurse)[1][0]['handover'],'completed')
  self.assertEqual(self.req('duty-shifts',cookie=self.second)[1],[])
 def test_leave_requires_arranged_coverage(self):
  (nurse,nid),(other,oid),_=self.caregivers();start='2026-12-01T08:00:00+00:00';end='2026-12-01T16:00:00+00:00';shift=self.shift(nid,start,end)
  leave=self.create('staff-leave',{'starts_at':start,'ends_at':end,'reason':'Synthetic planned leave'},nurse)
  self.assertEqual(self.req('staff-leave','PATCH',{'id':leave['id'],'status':'approved'},self.first)[0],400)
  self.assertEqual(self.req('duty-shifts','PATCH',{'id':shift['id'],'version':1,'action':'replace','replacement_id':oid},self.first)[0],200)
  self.assertEqual(self.req('staff-leave','PATCH',{'id':leave['id'],'status':'approved'},self.first)[0],200)
  self.assertEqual(self.req('duty-shifts','POST',{'staff_id':nid,'department':'Ward','shift_name':'Conflicting leave','starts_at':start,'ends_at':end},self.first)[0],400)
 def test_shift_swap_requires_colleague_acceptance_and_admin_approval(self):
  (nurse,nid),(other,oid),_=self.caregivers()
  a=self.shift(nid,'2026-12-02T08:00:00+00:00','2026-12-02T16:00:00+00:00');b=self.shift(oid,'2026-12-03T08:00:00+00:00','2026-12-03T16:00:00+00:00')
  swap=self.create('shift-swaps',{'shift_id':a['id'],'target_shift_id':b['id']},nurse)
  self.assertEqual(self.req('shift-swaps','PATCH',{'id':swap['id'],'action':'approve'},self.first)[0],400)
  self.assertEqual(self.req('shift-swaps','PATCH',{'id':swap['id'],'action':'accept'},nurse)[0],400)
  self.assertEqual(self.req('shift-swaps','PATCH',{'id':swap['id'],'action':'accept'},other)[0],200)
  self.assertEqual(self.req('shift-swaps','PATCH',{'id':swap['id'],'action':'approve'},self.first)[0],200)
  shifts=self.req('duty-shifts',cookie=self.first)[1];self.assertEqual(next(s['staff_id'] for s in shifts if s['id']==a['id']),oid)
 def test_supervisor_dashboard_is_tenant_scoped(self):
  p=self.patient();self.create('encounters',{'patient_id':p['id'],'department':'Ward'})
  self.assertEqual(self.req('coverage',cookie=self.first)[1]['unassigned_inpatients'][0]['id'],p['id'])
  self.assertEqual(self.req('coverage',cookie=self.second)[1]['unassigned_inpatients'],[])
