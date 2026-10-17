import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

PASSWORD='synthetic-password-123'

class TenantIsolation(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();server.DB=self.tmp.name+'/hospital.db';server.init_db();server.LOGIN_ATTEMPTS.clear()
  with server.connect() as c:c.execute("INSERT INTO hospitals(id,name,slug) VALUES(2,'Second Hospital','second')")
  server.add_user('firstadmin',PASSWORD,'admin',hospital_id=1)
  server.add_user('secondadmin',PASSWORD,'admin',hospital_id=2)
  server.add_user('platform',PASSWORD,'super_admin')
  self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
  threading.Thread(target=self.http.serve_forever,daemon=True).start()
  self.base='http://127.0.0.1:'+str(self.http.server_port)
  self.first=self.login('firstadmin');self.second=self.login('secondadmin');self.platform=self.login('platform')
 def tearDown(self):self.http.shutdown();self.http.server_close();self.tmp.cleanup()
 def req(self,path,method='GET',data=None,cookie=''):
  req=urllib.request.Request(self.base+'/api/'+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','Cookie':cookie,'X-Requested-With':'OlamideMedical'})
  try:
   with urllib.request.urlopen(req) as r:return r.status,json.load(r),r.headers
  except urllib.error.HTTPError as e:return e.code,json.load(e),e.headers
 def login(self,name):
  status,body,headers=self.req('login','POST',{'username':name,'password':PASSWORD});self.assertEqual(status,200,body);return headers['Set-Cookie'].split(';')[0]
 def create(self,table,data,cookie=None):
  status,row,_=self.req(table,'POST',data,cookie or self.first);self.assertEqual(status,200,row);return row
 def patient(self,cookie=None):return self.create('patients',{'name':'Synthetic patient','dob':'1990-01-01','mrn':'LOCAL-001'},cookie)
 def test_every_module_list_and_update_is_scoped(self):
  p=self.patient();q=self.patient(self.second)
  for table in server.MODULES:
   with self.subTest(table=table):
    if table!='patients':
     with server.connect() as c:c.execute(f'INSERT INTO {table}(hospital_id) VALUES(2)')
    rows=self.req(table,cookie=self.first)[1];self.assertTrue(all(r['hospital_id']==1 for r in rows))
    foreign=q['id'] if table=='patients' else 1
    self.assertEqual(self.req(table+'/'+str(foreign),cookie=self.first)[1],[])
    self.assertEqual(self.req(table+'/'+str(foreign),'PATCH',{'version':1},self.first)[0],404)
  self.assertEqual(self.req('patients/'+str(p['id']),'PATCH',{'name':'Changed','version':1},self.first)[0],200)
 def test_cross_hospital_relationships_rejected_by_api_and_database(self):
  p=self.patient();q=self.patient(self.second)
  foreign_stock=self.create('inventory',{'name':'Foreign stock','quantity':5},self.second)
  foreign_invoice=self.create('invoices',{'patient_id':q['id'],'amount_cents':100},self.second)
  for table,data in [('appointments',{'patient_id':q['id'],'provider':'A','department':'Clinic','scheduled_at':'2026-11-01T10:00'}),('prescriptions',{'patient_id':p['id'],'inventory_id':foreign_stock['id']}),('payments',{'invoice_id':foreign_invoice['id'],'amount_cents':10})]:
   self.assertEqual(self.req(table,'POST',data,self.first)[0],400)
  with server.connect() as c:
   with self.assertRaises(sqlite3.IntegrityError):c.execute('INSERT INTO encounters(hospital_id,patient_id) VALUES(1,?)',(q['id'],))
   with self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE patients SET hospital_id=2 WHERE id=?',(p['id'],))
 def test_mrn_and_provider_schedule_are_hospital_local_and_restart_safe(self):
  p=self.patient();q=self.patient(self.second)
  for patient,cookie in [(p,self.first),(q,self.second)]:self.create('appointments',{'patient_id':patient['id'],'provider':'Doctor A','department':'Clinic','scheduled_at':'2026-11-01T10:00'},cookie)
  server.init_db();server.init_db()
  self.assertEqual(len(self.req('patients',cookie=self.first)[1]),1)
 def test_platform_control_plane_and_no_clinical_access(self):
  self.assertEqual(self.req('hospitals',cookie=self.first)[0],403)
  self.assertEqual(self.req('patients',cookie=self.platform)[0],403)
  hospital=self.create('hospitals',{'name':'New Hospital','slug':'new-hospital'},self.platform)
  account=self.create('hospital-users',{'username':'newadmin','password':PASSWORD,'role':'admin','hospital_id':hospital['id']},self.platform)
  self.assertEqual(account['hospital_id'],hospital['id']);self.assertNotIn('password_hash',account)
  self.assertEqual(self.req('hospital-users','POST',{'username':'bad','password':PASSWORD,'role':'super_admin','hospital_id':1},self.first)[0],400)
  self.assertEqual(self.req('patients','POST',{'name':'Injected','dob':'1990-01-01','hospital_id':2},self.first)[0],400)
 def test_hospital_suspend_revokes_sessions_and_blocks_login(self):
  hospitals=self.req('hospitals',cookie=self.platform)[1];h=next(h for h in hospitals if h['id']==2)
  self.assertEqual(self.req('hospitals','PATCH',{'id':2,'version':h['version'],'active':False},self.platform)[0],200)
  self.assertEqual(self.req('me',cookie=self.second)[0],401)
  self.assertEqual(self.req('login','POST',{'username':'secondadmin','password':PASSWORD})[0],401)
  self.assertEqual(self.req('me',cookie=self.first)[0],200)
  self.assertEqual(self.req('hospitals','PATCH',{'id':2,'version':h['version'],'active':True},self.platform)[0],409)
 def test_hospital_admin_cannot_manage_other_tenants(self):
  rows=self.req('hospital-users',cookie=self.first)[1];self.assertEqual([r['username'] for r in rows],['firstadmin'])
  target=next(r for r in self.req('hospital-users',cookie=self.platform)[1] if r['username']=='secondadmin')
  self.assertEqual(self.req('hospital-users','PATCH',{'id':target['id'],'active':False},self.first)[0],404)
  self.assertEqual(self.req('hospital-users','POST',{'username':'intruder','password':PASSWORD,'role':'admin','hospital_id':2},self.first)[0],400)
  self.assertEqual(self.req('hospital-users','PATCH',{'id':target['id'],'active':False},self.platform)[0],400)
 def test_password_reset_revokes_prior_session(self):
  account=self.create('hospital-users',{'username':'clinician1','password':PASSWORD,'role':'clinician'},self.first)
  cookie=self.login('clinician1')
  self.assertEqual(self.req('hospital-users','PATCH',{'id':account['id'],'password':'new-synthetic-password-456'},self.first)[0],200)
  self.assertEqual(self.req('me',cookie=cookie)[0],401)
  self.assertEqual(self.req('login','POST',{'username':'clinician1','password':PASSWORD})[0],401)
 def test_audits_are_hospital_scoped(self):
  self.patient();self.patient(self.second)
  for path in ('audit','tenant-audit'):
   self.assertTrue(all(r['hospital_id']==1 for r in self.req(path,cookie=self.first)[1]))
  self.assertEqual(self.req('audit',cookie=self.platform)[0],403)
 def test_patient_account_cannot_bind_foreign_patient(self):
  q=self.patient(self.second)
  self.assertEqual(self.req('hospital-users','POST',{'username':'badpatient','password':PASSWORD,'role':'patient','patient_id':q['id']},self.first)[0],400)
  with self.assertRaises(ValueError):server.add_user('badpatient',PASSWORD,'patient',q['id'],1)

class LegacyMigration(unittest.TestCase):
 def test_existing_data_remains_under_default_hospital_without_elevation(self):
  with tempfile.TemporaryDirectory() as folder:
   server.DB=folder+'/legacy.db'
   with sqlite3.connect(server.DB) as c:
    c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL,patient_id INTEGER)')
    c.execute("INSERT INTO users VALUES(1,'legacy','salt','hash','admin',NULL)")
    c.execute('CREATE TABLE patients(id INTEGER PRIMARY KEY,mrn TEXT,name TEXT,dob TEXT)')
    c.execute("INSERT INTO patients VALUES(1,'OLD','Legacy patient','1990-01-01')")
   server.init_db();server.init_db()
   with server.connect() as c:
    self.assertEqual(c.execute('SELECT hospital_id FROM patients').fetchone()[0],1)
    u=c.execute('SELECT * FROM users').fetchone();self.assertEqual(u['hospital_id'],1);self.assertEqual(u['role'],'admin')
