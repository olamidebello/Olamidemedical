import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parent))
import test_tenancy as fixtures
import providers
import registration

class ProviderManagement(unittest.TestCase):
 tearDown=fixtures.TenantIsolation.tearDown
 req=fixtures.TenantIsolation.req
 login=fixtures.TenantIsolation.login
 create=fixtures.TenantIsolation.create
 patient=fixtures.TenantIsolation.patient
 def setUp(self):
  fixtures.TenantIsolation.setUp(self);providers.ATTEMPTS.clear();registration.ATTEMPTS.clear()
 def apply(self):
  data={'hospital_slug':'existing-hospital','name':'Synthetic Provider','email':'provider@example.test','phone':'0000000000','profession':'doctor','specialty':'General','license_number':'SYNTHETIC-123','license_jurisdiction':'Synthetic jurisdiction','license_expiry':'2099-01-01'}
  status,result,_=self.req('provider-registration','POST',data);self.assertEqual(status,202,result)
  return self.req('provider-applications',cookie=self.first)[1][0]
 def test_application_review_registration_activation_and_suspension(self):
  application=self.apply()
  status,approval,_=self.req('provider-applications','POST',{'id':application['id'],'action':'approve','review_reference':'Synthetic credential review'},self.first);self.assertEqual(status,200,approval)
  credentials={'code':approval['invitation_code'],'username':'registereddoctor','password':fixtures.PASSWORD}
  self.assertEqual(self.req('register-user','POST',credentials)[0],200)
  self.assertEqual(self.req('login','POST',{'username':'registereddoctor','password':fixtures.PASSWORD})[0],401)
  profile=self.req('professionals',cookie=self.first)[1][0]
  self.assertEqual(profile['status'],'inactive');self.assertTrue(profile['user_id'])
  self.assertEqual(self.req('provider-management','PATCH',{'id':profile['id'],'version':profile['version'],'action':'activate'},self.first)[0],200)
  cookie=self.login('registereddoctor')
  profile=self.req('professionals',cookie=self.first)[1][0]
  self.assertEqual(self.req('provider-management','PATCH',{'id':profile['id'],'version':profile['version'],'action':'suspend'},self.first)[0],200)
  self.assertEqual(self.req('me',cookie=cookie)[0],401)
  self.assertEqual(self.req('login','POST',{'username':'registereddoctor','password':fixtures.PASSWORD})[0],401)
 def test_application_and_provider_administration_are_hospital_scoped(self):
  application=self.apply()
  self.assertEqual(self.req('provider-applications',cookie=self.second)[1],[])
  self.assertEqual(self.req('provider-applications','POST',{'id':application['id'],'action':'approve','review_reference':'Foreign review'},self.second)[0],409)
  self.assertEqual(self.req('provider-applications',cookie=self.platform)[0],403)
  self.assertEqual(self.req('provider-applications','POST',{'id':application['id'],'action':'reject','review_reference':'Synthetic review outcome'},self.first)[0],200)
  self.assertEqual(self.req('provider-applications','POST',{'id':application['id'],'action':'approve','review_reference':'Repeated review'},self.first)[0],409)
 def test_unreviewed_provider_cannot_be_activated_or_self_escalate(self):
  profile=self.create('professionals',{'name':'Synthetic Nurse','profession':'nurse'})
  self.assertEqual(self.req('provider-management','PATCH',{'id':profile['id'],'version':1,'action':'activate'},self.first)[0],400)
  self.assertEqual(self.req('professionals/'+str(profile['id']),'PATCH',{'version':1,'status':'active'},self.first)[0],400)
  self.assertEqual(self.req('provider-management','PATCH',{'id':profile['id'],'version':1,'action':'review','review_reference':'Insufficient evidence'},self.first)[0],400)
