"""Hospital onboarding, employee records and single-use account invitations."""
import hashlib
import re
import secrets
import time
import tenancy

ATTEMPTS={}


def initialize(c):
    for sql in [
      '''CREATE TABLE IF NOT EXISTS hospital_requests(id INTEGER PRIMARY KEY,name TEXT NOT NULL,slug TEXT NOT NULL,
        contact_name TEXT NOT NULL,email TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
        hospital_id INTEGER REFERENCES hospitals(id),created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
      '''CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY,hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
        employee_number TEXT NOT NULL,name TEXT NOT NULL,email TEXT NOT NULL,department TEXT NOT NULL DEFAULT '',
        job_title TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,user_id INTEGER UNIQUE REFERENCES users(id),
        version INTEGER NOT NULL DEFAULT 1,UNIQUE(hospital_id,employee_number))''',
      '''CREATE TABLE IF NOT EXISTS registration_invites(id INTEGER PRIMARY KEY,hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
        token_hash TEXT UNIQUE NOT NULL,role TEXT NOT NULL,patient_id INTEGER REFERENCES patients(id),
        employee_id INTEGER REFERENCES employees(id),expires INTEGER NOT NULL,used_at INTEGER,
        revoked INTEGER NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP)'''
    ]:c.execute(sql)
    if 'professional_id' not in {r['name'] for r in c.execute('PRAGMA table_info(registration_invites)')}:
        c.execute('ALTER TABLE registration_invites ADD COLUMN professional_id INTEGER REFERENCES professionals(id)')


def email(value):
    if not isinstance(value,str) or len(value)>200 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):raise ValueError('Valid contact email required')
    return value


def text(d,key,limit=150):
    value=d.get(key)
    if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('Valid '+key.replace('_',' ')+' required')
    return value.strip()


def invite(c,hid,role,patient_id,employee_id,actor,professional_id=None):
    if role not in tenancy.ROLES:raise ValueError('Hospital role required')
    if not tenancy.hospital(c,hid):raise ValueError('Active hospital required')
    if role=='patient' and not patient_id:raise ValueError('Patient invitation requires a local patient record')
    if role!='patient' and patient_id:raise ValueError('Patient links are reserved for patient accounts')
    if patient_id and not c.execute('SELECT 1 FROM patients WHERE id=? AND hospital_id=?',(patient_id,hid)).fetchone():raise ValueError('Patient must belong to this hospital')
    if employee_id:
        if role=='patient':raise ValueError('Patient invitation cannot be linked to an employee')
        if not c.execute('SELECT 1 FROM employees WHERE id=? AND hospital_id=? AND active=1 AND user_id IS NULL',(employee_id,hid)).fetchone():raise ValueError('Unlinked active employee in this hospital required')
    if professional_id and not c.execute("SELECT 1 FROM professionals WHERE id=? AND hospital_id=? AND user_id IS NULL AND status='inactive'",(professional_id,hid)).fetchone():raise ValueError('Unlinked inactive local provider required')
    token=secrets.token_urlsafe(32)
    cur=c.execute('INSERT INTO registration_invites(hospital_id,token_hash,role,patient_id,employee_id,expires,created_by,professional_id) VALUES(?,?,?,?,?,?,?,?)',(hid,hashlib.sha256(token.encode()).hexdigest(),role,patient_id,employee_id,int(time.time())+7*86400,actor,professional_id))
    return {'id':cur.lastrowid,'invitation_code':token,'expires_in_days':7}


def public(handler,c,path,method,hash_password):
    if path not in ('/api/register-hospital','/api/register-user'):return False
    if method!='POST':handler.send(405,{'error':'Use POST'});return True
    if handler.headers.get('X-Requested-With')!='OlamideMedical':handler.send(403,{'error':'Request verification required'});return True
    now=time.time();key=handler.client_address[0];attempts=[t for t in ATTEMPTS.get(key,[]) if t>now-3600];ATTEMPTS[key]=attempts
    if len(attempts)>=20:handler.send(429,{'error':'Registration attempt limit reached; retry later'});return True
    attempts.append(now);d=handler.body();c.execute('BEGIN IMMEDIATE')
    if path=='/api/register-hospital':
        if set(d)!={'name','slug','contact_name','email'}:raise ValueError('Hospital name, slug, contact name and email required')
        name=text(d,'name');slug=text(d,'slug',80);contact=text(d,'contact_name');contact_email=email(d.get('email'))
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug):raise ValueError('Slug must use lowercase letters, digits and hyphens')
        if c.execute("SELECT 1 FROM hospital_requests WHERE slug=? AND status='pending'",(slug,)).fetchone() or c.execute('SELECT 1 FROM hospitals WHERE slug=?',(slug,)).fetchone():raise ValueError('Hospital slug is unavailable')
        c.execute('INSERT INTO hospital_requests(name,slug,contact_name,email) VALUES(?,?,?,?)',(name,slug,contact,contact_email))
        handler.send(202,{'message':'Registration request submitted for platform administrator review. No account or hospital access is active yet.'});return True
    if set(d)!={'code','username','password'}:raise ValueError('Invitation code, username and password required')
    code=text(d,'code',200)
    invitation=c.execute('SELECT * FROM registration_invites WHERE token_hash=? AND used_at IS NULL AND revoked=0 AND expires>?',(hashlib.sha256(code.encode()).hexdigest(),int(now))).fetchone()
    if not invitation or not tenancy.hospital(c,invitation['hospital_id']):raise ValueError('Invalid, expired or used invitation')
    eid=invitation['employee_id']
    if eid and not c.execute('SELECT 1 FROM employees WHERE id=? AND hospital_id=? AND active=1 AND user_id IS NULL',(eid,invitation['hospital_id'])).fetchone():raise ValueError('Employee invitation is no longer eligible')
    professional_id=invitation['professional_id']
    if professional_id and not c.execute("SELECT 1 FROM professionals WHERE id=? AND hospital_id=? AND user_id IS NULL AND status='inactive'",(professional_id,invitation['hospital_id'])).fetchone():raise ValueError('Provider invitation is no longer eligible')
    user=tenancy.add_user(c,d.get('username'),d.get('password'),invitation['role'],invitation['hospital_id'],invitation['patient_id'],hash_password)
    c.execute('UPDATE registration_invites SET used_at=? WHERE id=?',(int(now),invitation['id']))
    if professional_id:
        c.execute('UPDATE professionals SET user_id=?,version=version+1 WHERE id=? AND hospital_id=?',(user['id'],professional_id,user['hospital_id']))
        c.execute('UPDATE users SET active=0 WHERE id=?',(user['id'],))
    if eid:c.execute('UPDATE employees SET user_id=?,version=version+1 WHERE id=?',(user['id'],eid))
    c.execute("INSERT INTO audit(actor,action,resource,record_id,hospital_id) VALUES(?,'invitation-register','user',?,?)",(user['username'],user['id'],user['hospital_id']))
    handler.send(200,{'message':'Provider account registered. Hospital administrator must activate it before sign-in.' if professional_id else 'Account registered. Sign in with your new username and password.'});return True


def handle(handler,c,u,path,method):
    if path=='/api/staff-directory':
        if method!='GET' or u['role'] in ('patient','super_admin'):handler.send(403,{'error':'Hospital staff access required'})
        else:handler.send(200,[dict(r) for r in c.execute('SELECT id,username,role FROM users WHERE hospital_id=? AND active=1 ORDER BY username',(u['hospital_id'],))])
        return True
    if path not in ('/api/registration-requests','/api/employees','/api/registration-invites'):return False
    platform=u['role']=='super_admin'
    if path=='/api/registration-requests':
        if not platform:handler.send(403,{'error':'Platform administrator required'});return True
        if method=='GET':handler.send(200,[dict(r) for r in c.execute('SELECT * FROM hospital_requests ORDER BY id DESC LIMIT 500')]);return True
        if method!='POST':handler.send(405,{'error':'Use POST'});return True
        d=handler.body();c.execute('BEGIN IMMEDIATE')
        request=c.execute("SELECT * FROM hospital_requests WHERE id=? AND status='pending'",(d.get('id'),)).fetchone()
        if not request:handler.send(409,{'error':'Pending request not found'});return True
        if d.get('action')=='reject':
            c.execute("UPDATE hospital_requests SET status='rejected' WHERE id=?",(request['id'],));result={'ok':True}
        elif d.get('action')=='approve':
            hid=c.execute('INSERT INTO hospitals(name,slug,contact_email) VALUES(?,?,?)',(request['name'],request['slug'],request['email'])).lastrowid
            result=invite(c,hid,'admin',None,None,u['username']);result['hospital_id']=hid
            c.execute("UPDATE hospital_requests SET status='approved',hospital_id=? WHERE id=?",(hid,request['id']))
        else:raise ValueError('Approve or reject the hospital request')
        handler.audit(c,u,'hospital-request-'+d['action'],'hospital-request',request['id']);handler.send(200,result);return True
    if u['role']!='admin':handler.send(403,{'error':'Hospital administrator required'});return True
    hid=u['hospital_id']
    if method=='GET':
        table='employees' if path=='/api/employees' else 'registration_invites'
        columns='*' if table=='employees' else 'id,hospital_id,role,patient_id,employee_id,expires,used_at,revoked,created_by'
        handler.send(200,[dict(r) for r in c.execute(f'SELECT {columns} FROM {table} WHERE hospital_id=? ORDER BY id DESC LIMIT 500',(hid,))]);return True
    d=handler.body();c.execute('BEGIN IMMEDIATE')
    if path=='/api/registration-invites':
        if method=='POST':
            if set(d)-{'role','patient_id','employee_id'}:raise ValueError('Unknown invitation field')
            result=invite(c,hid,d.get('role'),d.get('patient_id'),d.get('employee_id'),u['username'])
            handler.audit(c,u,'invite-create','invitation',result['id']);handler.send(200,result);return True
        if method=='PATCH' and set(d)=={'id','revoked'} and d['revoked'] is True:
            cur=c.execute('UPDATE registration_invites SET revoked=1 WHERE id=? AND hospital_id=?',(d['id'],hid))
            if not cur.rowcount:handler.send(404,{'error':'Invitation not found'});return True
            handler.audit(c,u,'invite-revoke','invitation',d['id']);handler.send(200,{'ok':True});return True
    elif method=='POST':
        if set(d)-{'employee_number','name','email','department','job_title'}:raise ValueError('Unknown employee field')
        number=text(d,'employee_number',80);name=text(d,'name');mail=email(d.get('email'))
        cur=c.execute('INSERT INTO employees(hospital_id,employee_number,name,email,department,job_title) VALUES(?,?,?,?,?,?)',(hid,number,name,mail,str(d.get('department',''))[:150],str(d.get('job_title',''))[:150]))
        handler.audit(c,u,'employee-register','employee',cur.lastrowid);handler.send(200,{'id':cur.lastrowid});return True
    elif method=='PATCH':
        if set(d)-{'id','version','active','name','email','department','job_title'}:raise ValueError('Unknown employee field')
        old=c.execute('SELECT * FROM employees WHERE id=? AND hospital_id=?',(d.get('id'),hid)).fetchone()
        if not old:handler.send(404,{'error':'Employee not found'});return True
        active=d.get('active',bool(old['active']))
        if not isinstance(active,bool):raise ValueError('Boolean employee state required')
        if old['user_id'] and not active and c.execute('SELECT active FROM users WHERE id=?',(old['user_id'],)).fetchone()[0]:raise ValueError('Suspend the linked user in Staff & access before changing employment status')
        name=d.get('name',old['name']);mail=email(d.get('email',old['email']))
        if not isinstance(name,str) or not name.strip() or len(name)>150:raise ValueError('Employee name required')
        cur=c.execute('UPDATE employees SET name=?,email=?,department=?,job_title=?,active=?,version=version+1 WHERE id=? AND hospital_id=? AND version=?',(name.strip(),mail,str(d.get('department',old['department']))[:150],str(d.get('job_title',old['job_title']))[:150],int(active),old['id'],hid,d.get('version')))
        if not cur.rowcount:handler.send(409,{'error':'Employee changed; refresh and retry'});return True
        handler.audit(c,u,'employee-update','employee',old['id']);handler.send(200,{'ok':True});return True
    handler.send(405,{'error':'Unsupported registration action'});return True
