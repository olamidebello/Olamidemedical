import unittest, tempfile, threading, urllib.request, urllib.error, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
class Workflows(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();server.DB=cls.tmp.name+'/test.db';server.init_db();server.add_user('admin','testing-password-123','admin');cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);threading.Thread(target=cls.http.serve_forever,daemon=True).start();cls.base='http://127.0.0.1:'+str(cls.http.server_port)
 @classmethod
 def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.tmp.cleanup()
 def request(self,path,method='GET',data=None,cookie=None):
  req=urllib.request.Request(self.base+'/api/'+path,data=json.dumps(data).encode() if data is not None else None,method=method,headers={'Cookie':cookie or getattr(self,'cookie',''),'Content-Type':'application/json','X-Requested-With':'OlamideMedical'})
  try:
   with urllib.request.urlopen(req) as r:return r.status,json.load(r),r.headers
  except urllib.error.HTTPError as e:return e.code,json.load(e),e.headers
 def setUp(self):
  _,_,h=self.request('login','POST',{'username':'admin','password':'testing-password-123'});self.cookie=h['Set-Cookie'].split(';')[0]
 def create(self,module,data):
  code,row,_=self.request(module,'POST',data);self.assertEqual(code,200,row);return row
 def test_patient_journey(self):
  p=self.create('patients',{'name':'Synthetic Patient','dob':'1990-01-01'})
  a=self.create('appointments',{'patient_id':p['id'],'provider':'Doctor A','department':'Clinic','scheduled_at':'2026-10-20T10:00'})
  self.assertEqual(self.request('appointments','POST',{'patient_id':p['id'],'provider':'Doctor A','department':'Clinic','scheduled_at':'2026-10-20T10:00'})[0],400)
  enc=self.create('encounters',{'patient_id':p['id'],'department':'Clinic'})
  n=self.create('notes',{'patient_id':p['id'],'encounter_id':enc['id'],'content':'Synthetic note','status':'signed'})
  self.assertEqual(self.request('notes/'+str(n['id']),'PATCH',{'content':'overwrite','version':1})[0],400)
  inv=self.create('invoices',{'patient_id':p['id'],'description':'Consultation','amount_cents':10000})
  self.create('payments',{'invoice_id':inv['id'],'amount_cents':4000})
  self.assertEqual(self.request('payments','POST',{'invoice_id':inv['id'],'amount_cents':7000})[0],400)
  self.create('payments',{'invoice_id':inv['id'],'amount_cents':6000})
  self.assertEqual(self.request('invoices/'+str(inv['id']))[1][0]['status'],'paid')
  self.assertEqual(self.request('appointments/'+str(a['id']),'PATCH',{'status':'completed','version':1})[0],200)
  self.assertEqual(self.request('appointments/'+str(a['id']),'PATCH',{'status':'cancelled','version':1})[0],409)
 def test_portal_isolation(self):
  p=self.create('patients',{'name':'Portal Patient','dob':'1985-01-01'});other=self.create('patients',{'name':'Other','dob':'1980-01-01'})
  server.add_user('portal','testing-password-123','patient',p['id']);_,_,h=self.request('login','POST',{'username':'portal','password':'testing-password-123'});cookie=h['Set-Cookie'].split(';')[0]
  self.assertEqual([r['id'] for r in self.request('patients',cookie=cookie)[1]],[p['id']])
  self.assertEqual(self.request('patients/'+str(other['id']),cookie=cookie)[1],[])
  self.assertEqual(self.request('inventory',cookie=cookie)[0],403)
  self.assertEqual(self.request('notes','POST',{'patient_id':p['id'],'content':'Forbidden'},cookie)[0],403)
 def test_cross_patient_links(self):
  a=self.create('patients',{'name':'Link A','dob':'2000-01-01'});b=self.create('patients',{'name':'Link B','dob':'2001-01-01'});o=self.create('orders',{'patient_id':a['id'],'description':'Synthetic test'})
  self.assertEqual(self.request('results','POST',{'patient_id':b['id'],'order_id':o['id'],'value':'5'})[0],400)
 def test_pharmacy_stock_transaction(self):
  p=self.create('patients',{'name':'Pharmacy patient','dob':'2000-01-01'})
  stock=self.create('inventory',{'name':'Synthetic medication','quantity':10,'reorder_level':2,'expiry':'2099-01-01'})
  rx=self.create('prescriptions',{'patient_id':p['id'],'inventory_id':stock['id'],'medication':'Synthetic medication','quantity':3,'status':'verified'})
  self.assertEqual(self.request('prescriptions/'+str(rx['id']),'PATCH',{'status':'dispensed','version':1})[0],200)
  self.assertEqual(self.request('inventory/'+str(stock['id']))[1][0]['quantity'],7)
  self.assertEqual(self.request('prescriptions/'+str(rx['id']),'PATCH',{'status':'dispensed','version':2})[0],400)
  self.assertEqual(self.request('inventory/'+str(stock['id']))[1][0]['quantity'],7)
if __name__=='__main__':unittest.main()
