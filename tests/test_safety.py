import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parent))
import test_tenancy as fixtures
import server

class SafetyWorkflows(unittest.TestCase):
 setUp=fixtures.TenantIsolation.setUp
 tearDown=fixtures.TenantIsolation.tearDown
 req=fixtures.TenantIsolation.req
 login=fixtures.TenantIsolation.login
 create=fixtures.TenantIsolation.create
 patient=fixtures.TenantIsolation.patient
 def test_result_acknowledgment_requires_owner_and_preserves_provenance(self):
  p=self.patient();server.add_user('resultowner',fixtures.PASSWORD,'clinician');owner=self.login('resultowner');uid=self.req('me',cookie=owner)[1]['id']
  server.add_user('otherdoctor',fixtures.PASSWORD,'clinician');other=self.login('otherdoctor')
  order=self.create('orders',{'patient_id':p['id'],'description':'Synthetic test'})
  result=self.create('results',{'patient_id':p['id'],'order_id':order['id'],'value':'Synthetic','status':'final'})
  task=self.create('critical_results',{'patient_id':p['id'],'result_id':result['id'],'assigned_user_id':uid,'severity':'urgent','due_at':'2026-11-01T00:00:00+00:00'})
  self.assertEqual(self.req('critical_results/'+str(task['id']),'PATCH',{'version':1,'status':'acknowledged','acknowledgment':'Synthetic readback'},other)[0],400)
  self.assertEqual(self.req('critical_results/'+str(task['id']),'PATCH',{'version':1,'status':'resolved','resolution':'Premature'},owner)[0],400)
  self.assertEqual(self.req('critical_results/'+str(task['id']),'PATCH',{'version':1,'status':'acknowledged','acknowledgment':'Synthetic readback'},owner)[0],200)
  acknowledged=self.req('critical_results/'+str(task['id']),cookie=owner)[1][0]
  self.assertEqual(acknowledged['acknowledged_by'],'resultowner');self.assertTrue(acknowledged['acknowledged_at'])
  self.assertEqual(self.req('critical_results/'+str(task['id']),'PATCH',{'version':2,'status':'resolved','resolution':'Synthetic clinician follow-up recorded'},owner)[0],200)
  self.assertEqual(self.req('critical_results/'+str(task['id']),'PATCH',{'version':3,'acknowledgment':'overwrite'},owner)[0],400)
  self.assertEqual(self.req('critical_results',cookie=self.second)[1],[])
 def test_reconciliation_and_closed_loop_referrals_require_documented_outcomes(self):
  p=self.patient();uid=self.req('me',cookie=self.first)[1]['id']
  referral=self.create('referrals',{'patient_id':p['id'],'specialty':'Synthetic specialty'})
  follow=self.create('referral_followups',{'patient_id':p['id'],'referral_id':referral['id'],'assigned_user_id':uid,'destination':'Synthetic destination','due_at':'2026-11-01T00:00:00+00:00'})
  self.assertEqual(self.req('referral_followups/'+str(follow['id']),'PATCH',{'version':1,'status':'completed'},self.first)[0],400)
  self.assertEqual(self.req('referral_followups/'+str(follow['id']),'PATCH',{'version':1,'status':'completed','acceptance_reference':'Synthetic acceptance','outcome':'Synthetic report received'},self.first)[0],200)
  review=self.create('medication_reviews',{'patient_id':p['id'],'source':'Synthetic interview','medication_list':'Synthetic list'})
  self.assertEqual(self.req('medication_reviews/'+str(review['id']),'PATCH',{'version':1,'status':'reviewed'},self.first)[0],400)
  self.assertEqual(self.req('medication_reviews/'+str(review['id']),'PATCH',{'version':1,'status':'reviewed','resolution':'Synthetic discrepancies reviewed'},self.first)[0],200)
  reviewed=self.req('medication_reviews/'+str(review['id']),cookie=self.first)[1][0];self.assertEqual(reviewed['reviewed_by'],'firstadmin')
  self.assertEqual(self.req('medication_reviews/'+str(review['id']),'PATCH',{'version':2,'resolution':'overwrite'},self.first)[0],400)
 def test_safety_overview_and_identity_candidates_are_local(self):
  p=self.patient();self.create('patients',{'name':p['name'],'dob':p['dob']})
  uid=self.req('me',cookie=self.first)[1]['id']
  self.create('transition_tasks',{'patient_id':p['id'],'assigned_user_id':uid,'task':'Synthetic follow-up','due_at':'2026-11-01T00:00:00+00:00'})
  summary=self.req('safety-overview',cookie=self.first)[1]
  self.assertEqual(summary['pending']['transition_tasks'],1);self.assertEqual(len(summary['identity_review_candidates']),1)
  other=self.req('safety-overview',cookie=self.second)[1];self.assertEqual(other['pending']['transition_tasks'],0);self.assertEqual(other['identity_review_candidates'],[])
  self.assertEqual(self.req('safety-overview',cookie=self.platform)[0],403)
