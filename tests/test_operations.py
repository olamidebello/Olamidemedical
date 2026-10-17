import unittest
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_tenancy as fixtures
import server
import registration
import clinical_ai

class ExpandedWorkflows(unittest.TestCase):
 setUp=fixtures.TenantIsolation.setUp
 tearDown=fixtures.TenantIsolation.tearDown
 req=fixtures.TenantIsolation.req
 login=fixtures.TenantIsolation.login
 create=fixtures.TenantIsolation.create
 patient=fixtures.TenantIsolation.patient
 def setUp(self):
  fixtures.TenantIsolation.setUp(self);registration.ATTEMPTS.clear();clinical_ai.RATE.clear()
 def test_hospital_registration_approval_and_single_use_invitation(self):
  code,_,_=self.req('register-hospital','POST',{'name':'Private Practice','slug':'private-practice','contact_name':'Synthetic owner','email':'owner@example.test'})
  self.assertEqual(code,202)
  self.assertEqual(self.req('registration-requests',cookie=self.first)[0],403)
  requests=self.req('registration-requests',cookie=self.platform)[1]
  approval=self.req('registration-requests','POST',{'id':requests[0]['id'],'action':'approve'},self.platform)[1]
  d={'code':approval['invitation_code'],'username':'practiceadmin','password':fixtures.PASSWORD}
  self.assertEqual(self.req('register-user','POST',d)[0],200)
  self.assertEqual(self.req('register-user','POST',{**d,'username':'replay'})[0],400)
  cookie=self.login('practiceadmin')
  self.assertEqual(self.req('me',cookie=cookie)[1]['hospital_id'],approval['hospital_id'])
  self.assertEqual(self.req('patients',cookie=cookie)[1],[])
 def test_employee_and_patient_registration_cannot_change_invited_role_or_tenant(self):
  e=self.create('employees',{'employee_number':'E1','name':'Synthetic Nurse','email':'nurse@example.test'})
  invitation=self.create('registration-invites',{'role':'nurse','employee_id':e['id']})
  d={'code':invitation['invitation_code'],'username':'nurseinvite','password':fixtures.PASSWORD}
  self.assertEqual(self.req('register-user','POST',{**d,'role':'super_admin'})[0],400)
  self.assertEqual(self.req('register-user','POST',d)[0],200)
  me=self.req('me',cookie=self.login('nurseinvite'))[1];self.assertEqual(me['role'],'nurse');self.assertEqual(me['hospital_id'],1)
  self.assertEqual(self.req('employees',cookie=self.second)[1],[])
  p=self.patient();inv=self.create('registration-invites',{'role':'patient','patient_id':p['id']})
  self.assertEqual(self.req('register-user','POST',{'code':inv['invitation_code'],'username':'newpatient','password':fixtures.PASSWORD})[0],200)
  self.assertEqual([r['id'] for r in self.req('patients',cookie=self.login('newpatient'))[1]],[p['id']])
 def test_insurance_claim_remittances_and_cross_patient_links(self):
  p=self.patient();payer=self.create('payers',{'name':'Synthetic Payer','payer_code':'TEST'})
  policy=self.create('policies',{'patient_id':p['id'],'payer_id':payer['id'],'member_id':'M1','coverage_start':'2026-01-01','coverage_end':'2027-01-01'})
  invoice=self.create('invoices',{'patient_id':p['id'],'description':'Synthetic visit','amount_cents':10000})
  claim=self.create('claims',{'patient_id':p['id'],'policy_id':policy['id'],'invoice_id':invoice['id'],'procedure_codes':'TEST','amount_cents':10000,'payer_reference':'manual-test-1','status':'submitted'})
  self.create('remittances',{'patient_id':p['id'],'claim_id':claim['id'],'amount_cents':8000,'adjustment_cents':2000,'reference':'R1'})
  self.assertEqual(self.req('claims/'+str(claim['id']),cookie=self.first)[1][0]['status'],'paid')
  self.assertEqual(self.req('remittances','POST',{'patient_id':p['id'],'claim_id':claim['id'],'amount_cents':1,'reference':'R2'},self.first)[0],400)
  self.assertEqual(self.req('claims',cookie=self.second)[1],[])
 def test_coupon_server_calculation_idempotency_and_charity(self):
  p=self.patient();invoice=self.create('invoices',{'patient_id':p['id'],'description':'Synthetic visit','amount_cents':10000})
  coupon=self.create('coupons',{'code':'CARE20','discount_type':'percent','discount_value':20,'usage_limit':1,'expires':'2099-01-01'})
  redemption=self.create('coupon_redemptions',{'patient_id':p['id'],'coupon_id':coupon['id'],'invoice_id':invoice['id'],'reference':'D1','discount_cents':9999})
  self.assertEqual(int(redemption['discount_cents']),2000)
  self.assertEqual(self.req('invoices/'+str(invoice['id']),cookie=self.first)[1][0]['amount_cents'],8000)
  self.assertEqual(self.req('coupon_redemptions','POST',{'patient_id':p['id'],'coupon_id':coupon['id'],'invoice_id':invoice['id'],'reference':'D2'},self.first)[0],400)
  charity=self.create('charities',{'name':'Synthetic foundation','registration_number':'EXAMPLE-1'})
  self.create('sponsorships',{'patient_id':p['id'],'charity_id':charity['id'],'invoice_id':invoice['id'],'amount_cents':1000,'reference':'Pledge1'})
 def test_professional_availability_and_knowledge_permissions(self):
  server.add_user('doctorone',fixtures.PASSWORD,'clinician')
  doctor=self.login('doctorone')
  uid=self.req('me',cookie=doctor)[1]['id']
  pro=self.create('professionals',{'user_id':uid,'name':'Synthetic doctor','profession':'doctor','specialty':'General','credential_status':'unverified'})
  self.create('availability',{'professional_id':pro['id'],'starts_at':'2026-11-01T10:00:00+00:00','ends_at':'2026-11-01T11:00:00+00:00','mode':'video'})
  self.assertEqual(self.req('availability','POST',{'professional_id':pro['id'],'starts_at':'2026-11-01T10:30:00+00:00','ends_at':'2026-11-01T11:30:00+00:00','mode':'video'},self.first)[0],400)
  self.create('knowledge_articles',{'title':'Synthetic protocol','content':'Synthetic workflow content','reviewed_by':'Test reviewer','status':'published'})
  self.create('staff_requests',{'title':'Consultation request','question':'Synthetic education question','urgency':'routine','assigned_user_id':uid})
  self.assertEqual(self.req('knowledge_articles',cookie=self.second)[1],[])
 def test_alert_audiences_and_ai_review_gate(self):
  server.add_user('billingone',fixtures.PASSWORD,'billing');billing=self.login('billingone')
  alert=self.create('alerts',{'title':'Clinical alert','message':'Synthetic message','severity':'warning','audience':'clinical'})
  self.assertEqual(self.req('alerts',cookie=billing)[1],[])
  self.assertEqual(self.req('alerts/'+str(alert['id']),'PATCH',{'status':'acknowledged','version':1},billing)[0],404)
  question={'question':'Explain the hospital synthetic protocol','confirm_no_patient_identifiers':True}
  self.assertEqual(self.req('ai-assist','POST',question,self.first)[0],403)
  h=self.req('hospitals',cookie=self.platform)[1][0]
  with server.connect() as c:c.execute('UPDATE hospitals SET ai_enabled=1 WHERE id=1')
  with patch.object(clinical_ai,'request_model',return_value='Synthetic educational draft'):
   response=self.req('ai-assist','POST',question,self.first);self.assertEqual(response[0],200);self.assertTrue(response[1]['review_required'])
  self.assertEqual(self.req('ai-assist','POST',{**question,'confirm_no_patient_identifiers':False},self.first)[0],400)
 def test_telemedicine_participant_consent_signaling_and_isolation(self):
  p=self.patient();server.add_user('visitdoctor',fixtures.PASSWORD,'clinician');doctor=self.login('visitdoctor');uid=self.req('me',cookie=doctor)[1]['id']
  server.add_user('visitpatient',fixtures.PASSWORD,'patient',p['id']);patient=self.login('visitpatient')
  visit=self.create('telemedicine',{'patient_id':p['id'],'provider_id':uid,'scheduled_at':'2026-11-01T10:00:00Z','reason':'Synthetic visit','mode':'video'})
  self.assertEqual(self.req('telemedicine-events?visit_id='+str(visit['id']),cookie=doctor)[0],400)
  self.assertEqual(self.req('telemedicine','PATCH',{'id':visit['id'],'action':'consent','consent_reference':'Synthetic consent'},patient)[0],200)
  self.assertEqual(self.req('telemedicine','PATCH',{'id':visit['id'],'action':'status','status':'waiting','version':2},patient)[0],200)
  event={'visit_id':visit['id'],'kind':'chat','payload':'Synthetic visit message'}
  self.assertEqual(self.req('telemedicine-events','POST',event,self.second)[0],404)
  self.assertEqual(self.req('telemedicine-events','POST',event,self.first)[0],403)
  self.assertEqual(self.req('telemedicine-events','POST',event,patient)[0],200)
  self.assertEqual(len(self.req('telemedicine-events?visit_id='+str(visit['id']),cookie=doctor)[1]['events']),1)
  self.assertEqual(self.req('telemedicine',cookie=self.second)[1],[])
