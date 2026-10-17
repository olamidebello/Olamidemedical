import os, sqlite3, json, secrets, hashlib, hmac, time, argparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

import tenancy
import mobility
import devices
import registration
import providers
import operations
import safety
operations.MODULES.update(safety.MODULES)
operations.STATES.update(safety.STATES)
operations.LINKS.update(safety.LINKS)
operations.CARE.update(safety.MODULES)
import telehealth
import ward
import clinical_ai
clinical_ai.load_local_environment()

ROOT=Path(__file__).parent
DB=os.environ.get('DATABASE_PATH',str(ROOT/'data/hospital.db'))
# Explicit field allowlists keep client-supplied SQL identifiers out of queries.
MODULES={
'patients': ['mrn','name','dob','phone','address','emergency_contact','insurance'],
'appointments':['patient_id','provider','department','scheduled_at','reason','status'],
'encounters':['patient_id','department','provider','status','diagnosis'],
'notes':['patient_id','encounter_id','category','content','status'],
'allergies':['patient_id','substance','reaction','severity'],
'medications':['patient_id','name','dose','route','frequency','status'],
'vitals':['patient_id','encounter_id','temperature','pulse','systolic','diastolic','oxygen','weight'],
'orders':['patient_id','encounter_id','kind','description','status'],
'results':['patient_id','order_id','value','unit','reference_range','status'],
'care_plans':['patient_id','goal','intervention','due_at','status'],
'referrals':['patient_id','specialty','reason','authorization','status'],
'beds':['unit','label','status','patient_id'],
'inventory':['name','sku','quantity','reorder_level','expiry'],
'prescriptions':['patient_id','inventory_id','medication','dose','quantity','status'],
'administrations':['patient_id','medication_id','dose','route','administered_at'],
'invoices':['patient_id','description','amount_cents','status'],
'payments':['invoice_id','amount_cents','reference'],
'messages':['patient_id','recipient','subject','content','status'],
'workqueues':['patient_id','title','assigned_to','priority','status'],
'specialty_cases':['patient_id','specialty','procedure','findings','status'],
'outreach':['patient_id','registry','care_gap','due_at','status'],
'documents':['patient_id','title','content','consent_status'],
'immunizations':['patient_id','vaccine','administered_at','lot'],
'history':['patient_id','category','description'],
'care_team':['patient_id','name','role','contact'],
}
MODULES.update(operations.MODULES)
tenancy.LINKS.update(operations.LINKS)
CLINICAL={'patients','encounters','notes','allergies','medications','vitals','orders','results','care_plans','referrals','administrations','specialty_cases','outreach','documents','immunizations','history','care_team','messages','workqueues'}
PERMISSIONS={
'super_admin':set(), 'admin':set(MODULES),'clinician':CLINICAL|{'appointments','beds','prescriptions'},
'nurse':CLINICAL-{'results'}|{'appointments','beds'},
'pharmacist':{'patients','allergies','medications','orders','inventory','prescriptions','messages'},
'reception':{'patients','appointments','referrals','encounters','documents','beds','messages'},
'billing':{'patients','invoices','payments','workqueues','messages'},
'patient':{'appointments','messages'} }
for role in ('admin','billing'):PERMISSIONS[role].update(operations.BILLING|{'alerts'})
for role in ('admin','clinician','nurse','pharmacist'):PERMISSIONS[role].update(operations.CARE)
STATES={'appointments':['scheduled','checked-in','completed','cancelled'], 'encounters':['open','discharged'], 'notes':['draft','signed'], 'orders':['draft','signed','released','completed','cancelled'], 'prescriptions':['pending','verified','dispensed','cancelled'], 'beds':['available','occupied','cleaning','maintenance'],'invoices':['open','paid','void'],'results':['preliminary','final'],'medications':['active','discontinued'],'care_plans':['active','completed'],'referrals':['pending','authorized','completed'],'workqueues':['open','in-progress','completed'],'messages':['unread','read'],'specialty_cases':['planned','in-progress','completed'],'outreach':['open','completed']}

STATES.update(operations.STATES)

def connect():
    c=sqlite3.connect(DB,timeout=20);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON'); return c

def password_hash(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()

def init_db():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL,patient_id INTEGER);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),expires INTEGER);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,resource TEXT,record_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);''')
        for table,fields in MODULES.items():
            cols=[]
            for f in fields:
                typ='INTEGER' if f.endswith('_id') or f in ('quantity','reorder_level','amount_cents') else 'TEXT'
                ref=' REFERENCES patients(id)' if f=='patient_id' else ' REFERENCES invoices(id)' if f=='invoice_id' else ' REFERENCES orders(id)' if f=='order_id' else ' REFERENCES encounters(id)' if f=='encounter_id' else ' REFERENCES medications(id)' if f=='medication_id' else ' REFERENCES inventory(id)' if f=='inventory_id' else ''
                cols.append(f'{f} {typ}{ref}')
            c.execute(f"CREATE TABLE IF NOT EXISTS {table}(id INTEGER PRIMARY KEY,{','.join(cols)},created_by TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,version INTEGER NOT NULL DEFAULT 1)")
            existing_columns={r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
            for field in fields:
                if field not in existing_columns:
                    column_type='INTEGER' if field.endswith('_id') or field in ('quantity','reorder_level','amount_cents') else 'TEXT'
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {field} {column_type}')
        tenancy.migrate(c, MODULES)
        mobility.initialize(c)
        devices.initialize(c)
        registration.initialize(c)
        providers.initialize(c)
        telehealth.initialize(c)
        ward.initialize(c)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS occupied_patient ON beds(patient_id) WHERE patient_id IS NOT NULL AND patient_id != ''")

def add_user(username,password,role,patient_id=None,hospital_id=1):
    if role=='super_admin':hospital_id=None
    with connect() as c:
        return tenancy.add_user(c,username,password,role,hospital_id,patient_id,password_hash)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass # Never log URLs or clinical payloads.
    def send(self,status,data):
        raw=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
    def body(self):
        length=int(self.headers.get('Content-Length','0'))
        if length>200000: raise ValueError('Request too large')
        data=json.loads(self.rfile.read(length) or '{}')
        if not isinstance(data,dict): raise ValueError('Expected an object')
        return data
    def user(self,c):
        token=self.headers.get('Cookie','').split('session=')[-1].split(';')[0]
        return c.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>? AND u.active=1 AND (u.role='super_admin' OR EXISTS(SELECT 1 FROM hospitals h WHERE h.id=u.hospital_id AND h.active=1))",(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
    def audit(self,c,u,action,resource,id=None):c.execute('INSERT INTO audit(actor,action,resource,record_id,hospital_id) VALUES(?,?,?,?,?)',(u['username'],action,resource,id,u['hospital_id']))
    def do_GET(self):self.handle_request('GET')
    def do_POST(self):self.handle_request('POST')
    def do_PATCH(self):self.handle_request('PATCH')
    def handle_request(self,method):
        try:self.route(method)
        except (ValueError,json.JSONDecodeError) as e:self.send(400,{'error':str(e)})
        except sqlite3.IntegrityError:self.send(409,{'error':'Duplicate record or invalid linked record'})
        except Exception:self.send(500,{'error':'Internal server error'})
    def route(self,method):
        path=urlparse(self.path).path
        if path=='/health':return self.send(200,{'status':'ok'})
        if not path.startswith('/api/'):
            if method!='GET' or path not in ('/', '/app.js', '/style.css', '/logo.png', '/developer-guide.html', '/user-guide.html', '/patient-guide.html', '/terms.html', '/privacy.html', '/copyright.html'):return self.send(404,{'error':'Not found'})
            file=ROOT/'static'/({'/':'index.html'}.get(path,path[1:]));raw=file.read_bytes()
            self.send_response(200);self.send_header('Content-Type',{'html':'text/html','js':'text/javascript','css':'text/css','png':'image/png'}[file.suffix[1:]]);self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'");self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw);return
        with connect() as c:
            if registration.public(self,c,path,method,password_hash):return
            if providers.public(self,c,path,method):return
            if path=='/api/device-ingest':
                if method!='POST':return self.send(405,{'error':'Use POST'})
                return devices.ingest(self,c)
            if path=='/api/login' and method=='POST':
                d=self.body(); key=self.client_address[0];now=time.time();attempts=LOGIN_ATTEMPTS.get(key,[]);attempts=[t for t in attempts if t>now-300];LOGIN_ATTEMPTS[key]=attempts
                if len(attempts)>=10:return self.send(429,{'error':'Too many attempts; retry in five minutes'})
                attempts.append(now);u=c.execute('SELECT * FROM users WHERE username=?',(d.get('username'),)).fetchone()
                if not u or not u['active'] or (u['role']!='super_admin' and not tenancy.hospital(c,u['hospital_id'])) or not hmac.compare_digest(u['password_hash'],password_hash(str(d.get('password','')),u['salt'])):return self.send(401,{'error':'Invalid credentials'})
                token=secrets.token_urlsafe(32);c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],now+28800));self.audit(c,u,'login','session')
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Set-Cookie',f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'+('; Secure' if os.environ.get('COOKIE_SECURE')=='1' else ''));self.end_headers();self.wfile.write(b'{"ok":true}');return
            u=self.user(c)
            if not u:return self.send(401,{'error':'Sign in required'})
            if method!='GET' and self.headers.get('X-Requested-With')!='OlamideMedical':return self.send(403,{'error':'Request verification required'})
            if path=='/api/logout':
                if method!='POST':return self.send(405,{'error':'Use POST to sign out'})
                c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],));return self.send(200,{'ok':True})
            if path=='/api/me':return self.send(200,{'id':u['id'],'username':u['username'],'role':u['role'],'patient_id':u['patient_id'],'modules':list(PERMISSIONS[u['role']]),'schema':MODULES,'states':STATES,'hospital_id':u['hospital_id'],'hospital':dict(tenancy.hospital(c,u['hospital_id'])) if u['hospital_id'] else None})
            if path in ('/api/hospitals','/api/hospital-users') and method!='GET':c.execute('BEGIN IMMEDIATE')
            if tenancy.management(self,c,u,path,method,password_hash):return
            if mobility.handle(self,c,u,path,method,PERMISSIONS[u["role"]],MODULES):return
            if devices.handle(self,c,u,path,method):return
            if registration.handle(self,c,u,path,method):return
            if providers.handle(self,c,u,path,method):return
            if telehealth.handle(self,c,u,path,method):return
            if clinical_ai.handle(self,c,u,path,method):return
            if ward.handle(self,c,u,path,method):return
            if safety.handle(self,c,u,path,method):return
            if path=='/api/audit':
                if u['role']!='admin':return self.send(403,{'error':'Administrator only'})
                return self.send(200,[dict(r) for r in c.execute('SELECT * FROM audit WHERE hospital_id=? ORDER BY id DESC LIMIT 500',(u['hospital_id'],))])
            parts=path.strip('/').split('/');table=parts[1];id=int(parts[2]) if len(parts)>2 else None
            if table not in MODULES:return self.send(404,{'error':'Unknown module'})
            portal=u['role']=='patient'
            portal_read={'patients','appointments','medications','results','care_plans','invoices','messages','immunizations','documents','care_team'}
            if table not in PERMISSIONS[u['role']] and not(portal and method=='GET' and table in portal_read):return self.send(403,{'error':'Role does not permit this action'})
            if method=='GET':
                where=['hospital_id=?'];params=[u['hospital_id']]
                if id:where.append('id=?');params.append(id)
                if portal:
                    where.append(('id' if table=='patients' else 'patient_id')+'=?');params.append(u['patient_id'])
                    if table=='results':where.append("status='final'")
                if table=='alerts' and u['role']!='admin':
                    where.append("(audience IN (?, 'staff') OR (audience='clinical' AND ? IN ('clinician','nurse','pharmacist')) OR assigned_user_id=?)");params.extend([u['role'],u['role'],u['id']])
                if table=='knowledge_articles' and u['role'] not in ('admin','clinician'):where.append("status='published'")
                query=parse_qs(urlparse(self.path).query)
                if query.get('patient_id') and 'patient_id' in MODULES[table]:where.append('patient_id=?');params.append(query['patient_id'][0])
                sql=f'SELECT * FROM {table}'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY id DESC LIMIT 500'
                rows=[dict(r) for r in c.execute(sql,params)];self.audit(c,u,'read',table,id);return self.send(200,rows)
            c.execute('BEGIN IMMEDIATE')
            stock_change=None
            d=self.body();fields=MODULES[table]
            if any(k not in fields+['version'] for k in d):raise ValueError('Unknown field')
            if portal:
                d['patient_id']=u['patient_id']
                if table=='appointments' and d.get('status','scheduled')!='scheduled':raise ValueError('Only scheduling is available in the portal')
            old=c.execute(f'SELECT * FROM {table} WHERE id=? AND hospital_id=?',(id,u['hospital_id'])).fetchone() if id else None
            if method=='PATCH' and not old:return self.send(404,{'error':'Record not found'})
            if portal and old and old['patient_id']!=u['patient_id']:return self.send(403,{'error':'Record belongs to another patient'})
            if old and table=='alerts' and u['role']!='admin' and old['audience'] not in (u['role'],'staff') and not (old['audience']=='clinical' and u['role'] in ('clinician','nurse','pharmacist')) and old['assigned_user_id']!=u['id']:return self.send(404,{'error':'Alert not found'})
            if old and ((table=='notes' and old['status']=='signed') or (table=='results' and old['status']=='final') or table in ('payments','administrations')):raise ValueError('Final record is immutable; create an addendum or correction record')
            merged=dict(old) if old else {};merged.update(d)
            if table in STATES:
                status=merged.get('status') or STATES[table][0]
                if status not in STATES[table]:raise ValueError('Invalid status')
                d['status']=status
            if 'patient_id' in fields and table!='beds' and not merged.get('patient_id'):raise ValueError('Patient is required')
            for field in ('quantity','reorder_level','amount_cents'):
                if field in d:
                    if isinstance(d[field],bool) or str(d[field])!=str(int(d[field])) or int(d[field])<0:raise ValueError(f'{field} must be a nonnegative integer')
                    d[field]=int(d[field])
            for link,target in tenancy.LINKS.items():
                if merged.get(link) and not c.execute(f'SELECT 1 FROM {target} WHERE id=? AND hospital_id=?',(merged[link],u['hospital_id'])).fetchone():raise ValueError('Linked record must belong to this hospital')
            for link,target in [('encounter_id','encounters'),('order_id','orders'),('medication_id','medications')]:
                if merged.get(link):
                    linked=c.execute(f'SELECT patient_id FROM {target} WHERE id=? AND hospital_id=?',(merged[link],u['hospital_id'])).fetchone()
                    if not linked or str(linked['patient_id'])!=str(merged.get('patient_id')):raise ValueError('Linked record must belong to the same patient')
            if table=='patients':
                if not merged.get('name') or not merged.get('dob'):raise ValueError('Patient name and date of birth required')
                if not old:d['mrn']=d.get('mrn') or 'OM-'+secrets.token_hex(5).upper()
            from datetime import datetime, date
            for f in ('dob','expiry'):
                if d.get(f):date.fromisoformat(d[f])
            if table=='appointments':
                if merged.get('scheduled_at'):datetime.fromisoformat(merged['scheduled_at'])
                if not all(merged.get(k) for k in ('provider','scheduled_at','department')):raise ValueError('Provider, date/time and department required')
                if merged.get('status')!='cancelled' and c.execute("SELECT id FROM appointments WHERE hospital_id=? AND provider=? AND scheduled_at=? AND status!='cancelled' AND id!=?",(u['hospital_id'],merged['provider'],merged['scheduled_at'],id or 0)).fetchone():raise ValueError('Provider is already booked at this time')
            if table=='beds':
                if (d['status']=='occupied')!=bool(merged.get('patient_id')):raise ValueError('Occupied bed requires a patient; other bed states require no patient')
            if table=='prescriptions' and d.get('status') in ('verified','dispensed') and u['role'] not in ('admin','pharmacist'):return self.send(403,{'error':'Pharmacist role required'})
            if table=='prescriptions' and d.get('status')=='dispensed':
                if u['role'] not in ('admin','pharmacist'):return self.send(403,{'error':'Pharmacist verification required'})
                if not old or old['status']!='verified':raise ValueError('Verify prescription before dispensing')
                stock=c.execute('SELECT * FROM inventory WHERE id=? AND hospital_id=?',(merged.get('inventory_id'),u['hospital_id'])).fetchone()
                quantity=int(merged.get('quantity') or 0)
                from datetime import date
                if not stock or quantity<=0 or stock['quantity']<quantity:raise ValueError('Select inventory with sufficient stock')
                if stock['expiry'] and stock['expiry']<date.today().isoformat():raise ValueError('Cannot dispense expired stock')
                stock_change=(quantity,stock['id'])
            if table=='prescriptions' and old and old['status']=='dispensed':raise ValueError('Dispensed prescription is immutable')
            if table=='invoices' and d.get('status')=='paid':raise ValueError('Invoice is marked paid by payment posting')
            if table=='payments':
                inv=c.execute('SELECT * FROM invoices WHERE id=? AND hospital_id=?',(d.get('invoice_id'),u['hospital_id'])).fetchone()
                if not inv or inv['status']!='open' or int(d.get('amount_cents',0))<=0:raise ValueError('Payment requires an open invoice and positive amount')
                paid=c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE invoice_id=? AND hospital_id=?',(inv['id'],u['hospital_id'])).fetchone()[0]
                if paid+d['amount_cents']>int(inv['amount_cents']):raise ValueError('Payment exceeds outstanding balance')
            merged.update(d)
            operations.validate(c,u,table,d,merged,old)
            safety.validate(c,u,table,d,merged,old)
            values={k:v for k,v in d.items() if k in fields}
            if method=='POST' and id is None:
                values['hospital_id']=u['hospital_id'];values['created_by']=u['username'];keys=list(values);cursor=c.execute(f"INSERT INTO {table}({','.join(keys)}) VALUES({','.join('?' for k in keys)})",list(values.values()));id=cursor.lastrowid
            elif method=='PATCH':
                if 'version' not in d:raise ValueError('Version is required to prevent overwriting concurrent changes')
                keys=list(values);cursor=c.execute(f"UPDATE {table} SET {','.join(k+'=?' for k in keys)},updated_at=CURRENT_TIMESTAMP,version=version+1 WHERE id=? AND version=? AND hospital_id=?",list(values.values())+[id,d['version'],u['hospital_id']])
                if not cursor.rowcount:return self.send(409,{'error':'Record changed. Refresh and retry.'})
            else:return self.send(405,{'error':'Unsupported action'})
            if stock_change:c.execute('UPDATE inventory SET quantity=quantity-?,version=version+1 WHERE id=? AND hospital_id=?',(*stock_change,u['hospital_id']))
            if table=='payments' and paid+d['amount_cents']==int(inv['amount_cents']):c.execute("UPDATE invoices SET status='paid',version=version+1 WHERE id=? AND hospital_id=?",(inv['id'],u['hospital_id']))
            written=c.execute(f'SELECT * FROM {table} WHERE id=? AND hospital_id=?',(id,u['hospital_id'])).fetchone()
            operations.after_write(c,u,table,written)
            self.audit(c,u,method.lower(),table,id);self.send(200,dict(c.execute(f'SELECT * FROM {table} WHERE id=? AND hospital_id=?',(id,u['hospital_id'])).fetchone()))

LOGIN_ATTEMPTS={}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8080);p.add_argument('--host',default='127.0.0.1');p.add_argument('--create-user');p.add_argument('--role',default='admin');p.add_argument('--patient-id',type=int);p.add_argument('--hospital-id',type=int,default=1);args=p.parse_args();init_db()
    if args.create_user:
        import getpass
        add_user(args.create_user,getpass.getpass('Password (12+ characters): '),args.role,args.patient_id,args.hospital_id)
    else:ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
