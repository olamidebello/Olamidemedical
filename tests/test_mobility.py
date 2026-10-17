import sqlite3
import time
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_tenancy as fixtures
PASSWORD=fixtures.PASSWORD
import server

class PatientMobility(unittest.TestCase):
 setUp=fixtures.TenantIsolation.setUp
 tearDown=fixtures.TenantIsolation.tearDown
 req=fixtures.TenantIsolation.req
 login=fixtures.TenantIsolation.login
 create=fixtures.TenantIsolation.create
 patient=fixtures.TenantIsolation.patient
 def enrolled(self):
  p=self.patient()
  row=self.create('mobility',{'action':'enroll','patient_id':p['id']})
  return p,row['identity_id'],row['portability_code']
 def grant(self,iid,target=2,cookie=None):
  return self.req('mobility','POST',{'action':'grant','identity_id':iid,'target_hospital_id':target,'consent_reference':'Synthetic signed consent 001'},cookie or self.first)
 def find(self,code,cookie=None):return self.req('mobility','POST',{'action':'find','code':code},cookie or self.second)
 def test_code_does_not_replace_authorization(self):
  p,iid,code=self.enrolled()
  self.assertEqual(self.find(code)[0],404)
  self.assertEqual(self.grant(iid)[0],200)
  self.assertEqual(self.find(code)[1]['profile']['name'],p['name'])
  self.assertEqual(self.req('mobility',cookie=self.platform)[0],403)
 def test_shared_charts_read_only_local_care_and_profile_updates(self):
  p,iid,code=self.enrolled()
  note=self.create('notes',{'patient_id':p['id'],'content':'Source hospital note','status':'signed'})
  self.create('notes',{'patient_id':p['id'],'content':'Unreleased draft','status':'draft'})
  self.grant(iid)
  shared=self.find(code)[1]
  self.assertEqual(len(shared['charts'][0]['records']['notes']),1)
  self.assertFalse(shared['charts'][0]['editable'])
  self.assertEqual(self.req('notes/'+str(note['id']),'PATCH',{'content':'foreign rewrite','version':1},self.second)[0],404)
  attached=self.create('mobility',{'action':'attach','identity_id':iid},self.second)
  own=self.create('notes',{'patient_id':attached['patient_id'],'content':'New visit at destination','status':'draft'},self.second)
  self.assertEqual(own['hospital_id'],2)
  self.assertEqual(self.req('notes/'+str(own['id']),'PATCH',{'content':'Local edit','version':1},self.second)[0],200)
  update={'action':'profile','identity_id':iid,'name':'Updated shared name','phone':'12345','version':1}
  self.assertEqual(self.req('mobility','POST',update,self.second)[0],200)
  self.assertEqual(self.req('mobility','POST',update,self.first)[0],409)
  self.assertEqual(self.find(code,self.first)[1]['profile']['name'],'Updated shared name')
  self.assertEqual(self.req('patients/'+str(p['id']),cookie=self.first)[1][0]['name'],p['name'])
  with server.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM mobility_profile_history').fetchone()[0],1)
 def test_revocation_and_expiry_remove_remote_access_preserve_local_chart(self):
  p,iid,code=self.enrolled();self.grant(iid)
  local=self.create('mobility',{'action':'attach','identity_id':iid},self.second)
  self.assertEqual(self.req('mobility','POST',{'action':'revoke','identity_id':iid,'target_hospital_id':2},self.first)[0],200)
  self.assertEqual(self.find(code)[0],404)
  self.assertEqual(len(self.req('patients/'+str(local['patient_id']),cookie=self.second)[1]),1)
  self.assertEqual(self.req('mobility',cookie=self.second)[1],[])
  self.grant(iid)
  with server.connect() as c:c.execute('UPDATE mobility_grants SET expires=?',(int(time.time())-1,))
  self.assertEqual(self.find(code)[0],404)
 def test_onward_sharing_does_not_grant_access_to_another_hospitals_chart(self):
  p,iid,code=self.enrolled();self.grant(iid)
  with server.connect() as c:c.execute("INSERT INTO hospitals(id,name,slug) VALUES(3,'Third hospital','third')")
  server.add_user('thirdadmin',PASSWORD,'admin',hospital_id=3);third=self.login('thirdadmin')
  self.create('mobility',{'action':'attach','identity_id':iid},self.second)
  self.assertEqual(self.grant(iid,3,self.second)[0],200)
  shared=self.find(code,third)[1]
  self.assertEqual([chart['hospital_id'] for chart in shared['charts']],[2])
  self.assertEqual(self.req('patients/'+str(p['id']),cookie=third)[1],[])
  self.assertEqual(self.req('mobility','POST',{'action':'revoke','identity_id':iid,'target_hospital_id':2},self.first)[0],200)
  self.assertEqual(self.req('mobility','POST',{'action':'revoke','identity_id':iid,'target_hospital_id':3},self.second)[0],200)
  self.assertEqual(self.find(code,third)[0],404)
 def test_matching_existing_identity_and_no_foreign_attach(self):
  p,iid,code=self.enrolled();self.grant(iid)
  self.assertEqual(self.req('mobility','POST',{'action':'attach','identity_id':iid,'patient_id':p['id']},self.second)[0],400)
  q=self.patient(self.second)
  attached=self.create('mobility',{'action':'attach','identity_id':iid,'patient_id':q['id']},self.second)
  self.assertEqual(attached['patient_id'],q['id'])
  self.assertEqual(self.req('mobility','POST',{'action':'attach','identity_id':iid},self.second)[0],400)
 def test_grant_requires_documented_authorization_and_expiry(self):
  p,iid,code=self.enrolled()
  for changes in ({'consent_reference':''},{'expires':int(time.time())-5}):
   d={'action':'grant','identity_id':iid,'target_hospital_id':2,'consent_reference':'Synthetic consent'};d.update(changes)
   self.assertEqual(self.req('mobility','POST',d,self.first)[0],400)
  self.assertEqual(self.find(code)[0],404)
