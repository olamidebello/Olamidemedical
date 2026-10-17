"""Hospital isolation, legacy migration and administrative account operations."""
import re
import secrets

ROLES = ('admin', 'clinician', 'nurse', 'pharmacist', 'reception', 'billing', 'patient')
LINKS = {'patient_id':'patients', 'encounter_id':'encounters', 'order_id':'orders',
         'medication_id':'medications', 'inventory_id':'inventory', 'invoice_id':'invoices'}


def migrate(c, modules):
    c.execute('BEGIN IMMEDIATE')
    c.execute('''CREATE TABLE IF NOT EXISTS hospitals(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, contact_email TEXT NOT NULL DEFAULT '',
        version INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    if 'organization_type' not in {r['name'] for r in c.execute('PRAGMA table_info(hospitals)')}:
        c.execute("ALTER TABLE hospitals ADD COLUMN organization_type TEXT NOT NULL DEFAULT 'hospital'")
    if 'ai_enabled' not in {r['name'] for r in c.execute('PRAGMA table_info(hospitals)')}:
        c.execute("ALTER TABLE hospitals ADD COLUMN ai_enabled INTEGER NOT NULL DEFAULT 0")
    c.execute("INSERT OR IGNORE INTO hospitals(id,name,slug) VALUES(1,'Existing Hospital','existing-hospital')")
    for table in ['users', 'audit', *modules]:
        columns={r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
        if 'hospital_id' not in columns:
            c.execute(f'ALTER TABLE {table} ADD COLUMN hospital_id INTEGER DEFAULT 1')
        c.execute(f'CREATE INDEX IF NOT EXISTS {table}_hospital ON {table}(hospital_id)')
    if 'active' not in {r['name'] for r in c.execute('PRAGMA table_info(users)')}:
        c.execute('ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
    c.execute('DROP INDEX IF EXISTS mrn_unique')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS mrn_hospital_unique ON patients(hospital_id,mrn)')
    # Database guards complement scoped HTTP queries and prevent cross-hospital links.
    for table, fields in {'users':['patient_id'], **modules}.items():
        for action in ('INSERT','UPDATE'):
            checks=["SELECT CASE WHEN NEW.role='super_admin' AND (NEW.hospital_id IS NOT NULL OR NEW.patient_id IS NOT NULL) THEN RAISE(ABORT,'Platform account cannot belong to a hospital') END;"] if table=='users' else []
            condition="NEW.role!='super_admin' AND " if table=='users' else ''
            checks.append(f"SELECT CASE WHEN {condition}(NEW.hospital_id IS NULL OR NOT EXISTS(SELECT 1 FROM hospitals WHERE id=NEW.hospital_id)) THEN RAISE(ABORT,'Hospital required') END;")
            if action=='UPDATE':
                checks.append("SELECT CASE WHEN NEW.hospital_id IS NOT OLD.hospital_id THEN RAISE(ABORT,'Hospital reassignment is forbidden') END;")
            for field in fields:
                if field in LINKS:
                    target=LINKS[field]
                    checks.append(f"SELECT CASE WHEN NEW.{field} IS NOT NULL AND NEW.{field} != '' AND NOT EXISTS(SELECT 1 FROM {target} WHERE id=NEW.{field} AND hospital_id=NEW.hospital_id) THEN RAISE(ABORT,'Cross-hospital reference forbidden') END;")
            c.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_tenant_{action.lower()} BEFORE {action} ON {table} BEGIN {' '.join(checks)} END")


def hospital(c, hospital_id):
    return c.execute('SELECT * FROM hospitals WHERE id=? AND active=1',(hospital_id,)).fetchone()


def public_user(row):
    return {k:row[k] for k in ('id','username','role','patient_id','hospital_id','active')}


def add_user(c, username, password, role, hospital_id, patient_id, hash_password):
    if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_.@+-]{3,100}',username):
        raise ValueError('Username must be 3–100 letters, digits or . _ @ + -')
    if role not in (*ROLES,'super_admin') or not isinstance(password,str) or len(password)<12:
        raise ValueError('Known role and password of at least 12 characters required')
    if role=='super_admin':
        if hospital_id is not None or patient_id is not None:raise ValueError('Platform account cannot belong to a hospital')
    elif not hospital(c,hospital_id):raise ValueError('Active hospital required')
    if role=='patient' and not patient_id:raise ValueError('Patient account requires a patient')
    if patient_id and not c.execute('SELECT 1 FROM patients WHERE id=? AND hospital_id=?',(patient_id,hospital_id)).fetchone():
        raise ValueError('Patient must belong to this hospital')
    salt=secrets.token_hex(16)
    cursor=c.execute('INSERT INTO users(username,salt,password_hash,role,patient_id,hospital_id) VALUES(?,?,?,?,?,?)',
                    (username,salt,hash_password(password,salt),role,patient_id,hospital_id))
    return public_user(c.execute('SELECT * FROM users WHERE id=?',(cursor.lastrowid,)).fetchone())


def management(handler, c, u, path, method, hash_password):
    """Return True when an administrative route has been handled."""
    if path not in ('/api/hospitals','/api/hospital-users','/api/tenant-audit'):return False
    platform=u['role']=='super_admin'
    if not platform and u['role']!='admin':
        handler.send(403,{'error':'Administrator access required'});return True
    if path=='/api/tenant-audit':
        if method!='GET':handler.send(405,{'error':'Read only'})
        else:
            where='' if platform else ' WHERE hospital_id=?'
            handler.send(200,[dict(r) for r in c.execute('SELECT * FROM audit'+where+' ORDER BY id DESC LIMIT 500',() if platform else (u['hospital_id'],))])
        return True
    if path=='/api/hospitals':
        if not platform:handler.send(403,{'error':'Platform administrator required'});return True
        if method=='GET':
            handler.send(200,[dict(r) for r in c.execute('''SELECT h.*,
                (SELECT COUNT(*) FROM users WHERE hospital_id=h.id) AS users,
                (SELECT COUNT(*) FROM patients WHERE hospital_id=h.id) AS patients
                FROM hospitals h ORDER BY h.name''')]);return True
        d=handler.body()
        if set(d)-{'id','name','slug','contact_email','active','version','organization_type','ai_enabled'}:raise ValueError('Unknown hospital field')
        if method=='POST':
            name=d.get('name','').strip();slug=d.get('slug','')
            if not name or len(name)>150 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) or len(slug)>80:raise ValueError('Hospital name and lowercase URL slug required')
            kind=d.get('organization_type','hospital')
            if kind not in ('hospital','private_doctor','private_nurse','clinic'):raise ValueError('Valid organization type required')
            cursor=c.execute('INSERT INTO hospitals(name,slug,contact_email,organization_type) VALUES(?,?,?,?)',(name,slug,str(d.get('contact_email',''))[:200],kind))
            handler.audit(c,u,'create','hospital',cursor.lastrowid)
            handler.send(200,dict(c.execute('SELECT * FROM hospitals WHERE id=?',(cursor.lastrowid,)).fetchone()));return True
        if method=='PATCH':
            old=c.execute('SELECT * FROM hospitals WHERE id=?',(d.get('id'),)).fetchone()
            if not old:handler.send(404,{'error':'Hospital not found'});return True
            ai=d.get('ai_enabled',bool(old['ai_enabled']))
            if not isinstance(ai,bool):raise ValueError('AI enabled must be boolean')
            name=d.get('name',old['name']);active=d.get('active',bool(old['active']))
            if not isinstance(name,str) or not name.strip() or len(name)>150 or not isinstance(active,bool):raise ValueError('Valid name and boolean active state required')
            cur=c.execute('UPDATE hospitals SET name=?,contact_email=?,active=?,ai_enabled=?,version=version+1 WHERE id=? AND version=?',(name.strip(),str(d.get('contact_email',old['contact_email']))[:200],int(active),int(ai),old['id'],d.get('version')))
            if not cur.rowcount:handler.send(409,{'error':'Hospital changed; refresh and retry'});return True
            if not active:c.execute('DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE hospital_id=?)',(old['id'],))
            handler.audit(c,u,'update','hospital',old['id']);handler.send(200,{'ok':True});return True
        handler.send(405,{'error':'Unsupported action'});return True
    if method=='GET':
        where="role!='super_admin'" if platform else 'hospital_id=?'
        handler.send(200,[public_user(r) for r in c.execute('SELECT * FROM users WHERE '+where+' ORDER BY username',() if platform else (u['hospital_id'],))]);return True
    d=handler.body()
    if method=='POST':
        if set(d)-{'username','password','role','hospital_id','patient_id'}:raise ValueError('Unknown account field')
        hid=d.get('hospital_id') if platform else u['hospital_id']
        if not platform and 'hospital_id' in d and d['hospital_id']!=hid:raise ValueError('Cannot manage another hospital')
        if d.get('role') not in ROLES:raise ValueError('Hospital role required; platform accounts are CLI-only')
        row=add_user(c,d.get('username'),d.get('password'),d.get('role'),hid,d.get('patient_id'),hash_password)
        handler.audit(c,u,'create','hospital-user',row['id']);handler.send(200,row);return True
    if method=='PATCH':
        if set(d)-{'id','role','active','password','action'}:raise ValueError('Unknown account field')
        target=c.execute("SELECT * FROM users WHERE id=? AND role!='super_admin'",(d.get('id'),)).fetchone()
        if not target or (not platform and target['hospital_id']!=u['hospital_id']):handler.send(404,{'error':'Account not found'});return True
        role=d.get('role',target['role']);active=d.get('active',bool(target['active']))
        if role not in ROLES or not isinstance(active,bool):raise ValueError('Valid hospital role and boolean state required')
        if (role=='patient')!=(target['role']=='patient'):raise ValueError('Create a separate account when changing patient identity')
        if target['id']==u['id'] and (not active or role!=target['role']):raise ValueError('Cannot suspend or demote your own account')
        if target['role']=='admin' and target['active'] and (role!='admin' or not active):
            if c.execute("SELECT COUNT(*) FROM users WHERE hospital_id=? AND role='admin' AND active=1",(target['hospital_id'],)).fetchone()[0]<=1:raise ValueError('Keep at least one active hospital administrator')
        password=d.get('password')
        if password is not None and (not isinstance(password,str) or len(password)<12):raise ValueError('Password must contain at least 12 characters')
        if d.get('action') not in (None,'revoke_sessions'):raise ValueError('Unknown account action')
        c.execute('UPDATE users SET role=?,active=? WHERE id=?',(role,int(active),target['id']))
        if password is not None:
            salt=secrets.token_hex(16);c.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?',(salt,hash_password(password,salt),target['id']))
        c.execute('DELETE FROM sessions WHERE user_id=?',(target['id'],))
        handler.audit(c,u,'update','hospital-user',target['id']);handler.send(200,{'ok':True});return True
    handler.send(405,{'error':'Unsupported action'});return True
