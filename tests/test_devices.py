import json
import unittest
import urllib.request
import urllib.error
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_tenancy as fixtures
import server

class Devices(unittest.TestCase):
 setUp=fixtures.TenantIsolation.setUp
 tearDown=fixtures.TenantIsolation.tearDown
 req=fixtures.TenantIsolation.req
 login=fixtures.TenantIsolation.login
 create=fixtures.TenantIsolation.create
 patient=fixtures.TenantIsolation.patient
 def register(self,protocol='normalized-json'):
  return self.create('devices',{'name':'Synthetic monitor','protocol':protocol})
 def ingest(self,token,d):
  request=urllib.request.Request(self.base+'/api/device-ingest',data=json.dumps(d).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
  try:
   with urllib.request.urlopen(request) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def reading(self,p):return {'patient_id':p['id'],'message_id':'reading-001','code':'8867-4','value':72,'unit':'/min','observed_at':'2026-10-17T03:00:00Z'}
 def test_ingestion_duplicate_review_and_chart_ownership(self):
  p=self.patient();device=self.register();d=self.reading(p)
  code,r=self.ingest(device['token'],d);self.assertEqual(code,202,r)
  self.assertEqual(self.ingest(device['token'],d)[1]['duplicate'],True)
  self.assertEqual(self.ingest(device['token'],{**d,'value':80})[0],409)
  self.assertEqual(self.req('vitals',cookie=self.first)[1],[])
  self.assertEqual(self.req('device-readings',cookie=self.second)[1],[])
  self.assertEqual(self.req('device-review','POST',{'id':r['id'],'action':'accept'},self.second)[0],409)
  self.assertEqual(self.req('device-review','POST',{'id':r['id'],'action':'accept'},self.first)[0],200)
  self.assertEqual(self.req('device-review','POST',{'id':r['id'],'action':'accept'},self.first)[0],409)
  self.assertEqual(float(self.req('vitals',cookie=self.first)[1][0]['pulse']),72)
 def test_device_cannot_select_another_hospital_or_use_disabled_token(self):
  p=self.patient(self.second);device=self.register()
  self.assertEqual(self.ingest(device['token'],self.reading(p))[0],400)
  self.assertEqual(self.req('devices','PATCH',{'id':device['id'],'enabled':False},self.second)[0],404)
  self.assertEqual(self.req('devices','PATCH',{'id':device['id'],'enabled':False},self.first)[0],200)
  self.assertEqual(self.ingest(device['token'],self.reading(p))[0],401)
  self.assertEqual(self.req('devices',cookie=self.platform)[0],403)
 def test_fhir_mapping_rotation_and_rejection_of_wrong_units(self):
  p=self.patient();device=self.register('fhir-observation')
  d={'resourceType':'Observation','id':'fhir-001','status':'final','subject':{'reference':'Patient/'+str(p['id'])},'code':{'coding':[{'system':'http://loinc.org','code':'8310-5'}]},'effectiveDateTime':'2026-10-17T03:00:00Z','valueQuantity':{'value':98.6,'system':'http://unitsofmeasure.org','code':'[degF]'}}
  code,r=self.ingest(device['token'],d);self.assertEqual(code,202,r)
  self.assertEqual(self.req('device-review','POST',{'id':r['id'],'action':'accept'},self.first)[0],400)
  self.assertEqual(self.req('device-review','POST',{'id':r['id'],'action':'reject'},self.first)[0],200)
  result=self.req('devices','PATCH',{'id':device['id'],'action':'rotate'},self.first)[1]
  self.assertEqual(self.ingest(device['token'],d)[0],401)
  self.assertEqual(self.ingest(result['token'],d)[0],200)
  self.assertNotIn('token',self.req('devices',cookie=self.first)[1][0])
 def test_nonfinite_values_timezone_and_extra_fields_rejected(self):
  p=self.patient();device=self.register();d=self.reading(p)
  for invalid in ({'value':float('nan')},{'observed_at':'2026-10-17T03:00:00'},{'hospital_id':2}):
   self.assertEqual(self.ingest(device['token'],{**d,**invalid})[0],400)
