"""Consent-scoped patient portability; clinical chart ownership never changes."""
import hashlib
import secrets
import time
from datetime import date

STAFF = {'admin','clinician','nurse','pharmacist','reception'}
SHARED = {'patients','appointments','encounters','notes','allergies','medications','vitals','orders','results','care_plans','referrals','prescriptions','administrations','specialty_cases','immunizations','history','care_team'}


def initialize(c):
    statements = [
      '''CREATE TABLE IF NOT EXISTS mobility_identities(id INTEGER PRIMARY KEY,code_hash TEXT UNIQUE NOT NULL,
          owner_hospital_id INTEGER NOT NULL REFERENCES hospitals(id),name TEXT NOT NULL,dob TEXT NOT NULL,
          phone TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 1,updated_by TEXT,updated_hospital_id INTEGER,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
      '''CREATE TABLE IF NOT EXISTS mobility_links(identity_id INTEGER REFERENCES mobility_identities(id),
          hospital_id INTEGER REFERENCES hospitals(id),patient_id INTEGER UNIQUE REFERENCES patients(id),
          PRIMARY KEY(identity_id,hospital_id))''',
      '''CREATE TABLE IF NOT EXISTS mobility_grants(identity_id INTEGER REFERENCES mobility_identities(id),
          source_hospital_id INTEGER REFERENCES hospitals(id),target_hospital_id INTEGER REFERENCES hospitals(id),
          active INTEGER NOT NULL,expires INTEGER NOT NULL,consent_reference TEXT NOT NULL,granted_by TEXT NOT NULL,
          PRIMARY KEY(identity_id,source_hospital_id,target_hospital_id))''',
      '''CREATE TABLE IF NOT EXISTS mobility_profile_history(id INTEGER PRIMARY KEY,identity_id INTEGER REFERENCES mobility_identities(id),
          version INTEGER,name TEXT,dob TEXT,phone TEXT,actor TEXT,hospital_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
      '''CREATE TRIGGER IF NOT EXISTS mobility_link_guard BEFORE INSERT ON mobility_links BEGIN
          SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM patients WHERE id=NEW.patient_id AND hospital_id=NEW.hospital_id)
          THEN RAISE(ABORT,'Mobility link must match hospital patient') END; END'''
    ]
    for sql in statements:c.execute(sql)


def permitted(c, identity, hid):
    return identity['owner_hospital_id']==hid or c.execute('''SELECT 1 FROM mobility_grants g JOIN hospitals h ON h.id=g.source_hospital_id
        WHERE identity_id=? AND target_hospital_id=? AND g.active=1 AND g.expires>? AND h.active=1''',
        (identity['id'],hid,int(time.time()))).fetchone() is not None


def profile(identity):
    return {k:identity[k] for k in ('id','name','dob','phone','version','updated_by','updated_hospital_id','updated_at')}


def snapshot(c,identity,u,permissions,modules):
    hid=u['hospital_id'];result={'profile':profile(identity),'charts':[]}
    sources={hid}
    sources.update(r[0] for r in c.execute('''SELECT source_hospital_id FROM mobility_grants g JOIN hospitals h ON h.id=g.source_hospital_id
       WHERE identity_id=? AND target_hospital_id=? AND g.active=1 AND g.expires>? AND h.active=1''',(identity['id'],hid,int(time.time()))))
    for link in c.execute('''SELECT l.*,h.name AS hospital FROM mobility_links l JOIN hospitals h ON h.id=l.hospital_id
         WHERE identity_id=? AND h.active=1''',(identity['id'],)):
        if link['hospital_id'] not in sources:continue
        records={}
        for table in sorted(SHARED & permissions):
            column='id' if table=='patients' else 'patient_id'
            if column!='id' and column not in modules[table]:continue
            extra=" AND status='final'" if table=='results' else " AND status='signed'" if table=='notes' and link['hospital_id']!=hid else ''
            records[table]=[dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE {column}=? AND hospital_id=?'+extra+' ORDER BY id DESC LIMIT 500',(link['patient_id'],link['hospital_id']))]
        if u['role'] in ('admin','clinician','nurse'):
            records['clinical_entries']=[{**dict(r),'fields':__import__('json').loads(r['fields'])} for r in c.execute("SELECT * FROM clinical_entries WHERE patient_id=? AND hospital_id=? AND status='signed' ORDER BY care_at DESC LIMIT 500",(link['patient_id'],link['hospital_id']))]
        result['charts'].append({'hospital_id':link['hospital_id'],'hospital':link['hospital'],'patient_id':link['patient_id'],'editable':link['hospital_id']==hid,'records':records})
    return result


def handle(handler,c,u,path,method,permissions,modules):
    if path not in ('/api/mobility','/api/hospital-directory'):return False
    if u['role'] not in STAFF:handler.send(403,{'error':'Hospital care-team access required'});return True
    hid=u['hospital_id']
    if path=='/api/hospital-directory':
        if method!='GET':handler.send(405,{'error':'Read only'})
        else:handler.send(200,[dict(r) for r in c.execute('SELECT id,name,slug FROM hospitals WHERE active=1 ORDER BY name')])
        return True
    if method=='GET':
        rows=[]
        for row in c.execute('SELECT i.*,l.patient_id FROM mobility_identities i JOIN mobility_links l ON l.identity_id=i.id WHERE l.hospital_id=?',(hid,)):
            grants=[dict(g) for g in c.execute('SELECT target_hospital_id,active,expires FROM mobility_grants WHERE identity_id=? AND source_hospital_id=?',(row['id'],hid))]
            if permitted(c,row,hid):rows.append({**profile(row),'patient_id':row['patient_id'],'outgoing_grants':grants,'sharing_access':True})
            elif grants:
                local=c.execute('SELECT name,dob,phone FROM patients WHERE id=? AND hospital_id=?',(row['patient_id'],hid)).fetchone()
                rows.append({'id':row['id'],'name':local['name'],'dob':local['dob'],'phone':local['phone'],'patient_id':row['patient_id'],'outgoing_grants':grants,'sharing_access':False})
        handler.send(200,rows);return True
    if method!='POST':handler.send(405,{'error':'Use portability actions'});return True
    d=handler.body();action=d.get('action');c.execute('BEGIN IMMEDIATE')
    if action=='enroll':
        patient=c.execute('SELECT * FROM patients WHERE id=? AND hospital_id=?',(d.get('patient_id'),hid)).fetchone()
        if not patient:handler.send(404,{'error':'Local patient not found'});return True
        if c.execute('SELECT 1 FROM mobility_links WHERE patient_id=?',(patient['id'],)).fetchone():raise ValueError('Patient already enrolled or linked; use the existing identity')
        code=secrets.token_urlsafe(24)
        cur=c.execute('INSERT INTO mobility_identities(code_hash,owner_hospital_id,name,dob,phone,updated_by,updated_hospital_id) VALUES(?,?,?,?,?,?,?)',
                      (hashlib.sha256(code.encode()).hexdigest(),hid,patient['name'],patient['dob'],patient['phone'] or '',u['username'],hid))
        c.execute('INSERT INTO mobility_links VALUES(?,?,?)',(cur.lastrowid,hid,patient['id']))
        handler.audit(c,u,'mobility-enroll','patient-identity',cur.lastrowid)
        handler.send(200,{'identity_id':cur.lastrowid,'portability_code':code,'message':'Store this code securely; it is shown only once. A code alone does not authorize another hospital.'});return True
    if action=='find':
        code=d.get('code')
        if not isinstance(code,str) or len(code)>200:raise ValueError('Portability code required')
        identity=c.execute('SELECT * FROM mobility_identities WHERE code_hash=?',(hashlib.sha256(code.encode()).hexdigest(),)).fetchone()
    else:identity=c.execute('SELECT * FROM mobility_identities WHERE id=?',(d.get('identity_id'),)).fetchone()
    may_revoke=identity and action=='revoke' and c.execute('SELECT 1 FROM mobility_links WHERE identity_id=? AND hospital_id=?',(identity['id'],hid)).fetchone()
    if not identity or (not permitted(c,identity,hid) and not may_revoke):handler.send(404,{'error':'Shared patient not found or sharing has expired/revoked'});return True
    iid=identity['id']
    if action=='find':
        handler.audit(c,u,'mobility-read','patient-identity',iid);handler.send(200,snapshot(c,identity,u,permissions,modules));return True
    if action in ('grant','revoke'):
        if u['role'] not in ('admin','clinician'):handler.send(403,{'error':'Hospital administrator or clinician required'});return True
        if not c.execute('SELECT 1 FROM mobility_links WHERE identity_id=? AND hospital_id=?',(iid,hid)).fetchone():raise ValueError('You may share only your own hospital chart')
        target=d.get('target_hospital_id')
        if target==hid or not c.execute('SELECT 1 FROM hospitals WHERE id=? AND active=1',(target,)).fetchone():raise ValueError('Choose another active hospital')
        if action=='revoke':c.execute('UPDATE mobility_grants SET active=0 WHERE identity_id=? AND source_hospital_id=? AND target_hospital_id=?',(iid,hid,target))
        else:
            consent=d.get('consent_reference','');expires=d.get('expires',int(time.time())+30*86400)
            if not isinstance(consent,str) or not 3<=len(consent)<=500:raise ValueError('Documented patient authorization reference required')
            if not isinstance(expires,int) or isinstance(expires,bool) or not int(time.time())<expires<=int(time.time())+365*86400:raise ValueError('Sharing must expire within one year')
            c.execute('''INSERT INTO mobility_grants VALUES(?,?,?,?,?,?,?) ON CONFLICT(identity_id,source_hospital_id,target_hospital_id)
               DO UPDATE SET active=1,expires=excluded.expires,consent_reference=excluded.consent_reference,granted_by=excluded.granted_by''',(iid,hid,target,1,expires,consent,u['username']))
        handler.audit(c,u,'mobility-'+action,'patient-identity',iid);handler.send(200,{'ok':True});return True
    if action=='attach':
        if c.execute('SELECT 1 FROM mobility_links WHERE identity_id=? AND hospital_id=?',(iid,hid)).fetchone():raise ValueError('Patient already linked at this hospital')
        local_id=d.get('patient_id')
        if local_id:
            patient=c.execute('SELECT * FROM patients WHERE id=? AND hospital_id=?',(local_id,hid)).fetchone()
            if not patient or patient['dob']!=identity['dob'] or patient['name'].casefold().strip()!=identity['name'].casefold().strip():raise ValueError('Existing local patient name and date of birth must match; review identity before linking')
        else:
            local_id=c.execute('INSERT INTO patients(hospital_id,mrn,name,dob,phone,created_by) VALUES(?,?,?,?,?,?)',(hid,'OM-'+secrets.token_hex(5).upper(),identity['name'],identity['dob'],identity['phone'],u['username'])).lastrowid
        c.execute('INSERT INTO mobility_links VALUES(?,?,?)',(iid,hid,local_id))
        handler.audit(c,u,'mobility-attach','patient-identity',iid);handler.send(200,{'patient_id':local_id,'hospital_id':hid});return True
    if action=='profile':
        if u['role'] not in ('admin','clinician','reception'):handler.send(403,{'error':'Demographic editing role required'});return True
        if not c.execute('SELECT 1 FROM mobility_links WHERE identity_id=? AND hospital_id=?',(iid,hid)).fetchone():raise ValueError('Link a local patient before updating shared demographics')
        if set(d)-{'action','identity_id','name','dob','phone','version'}:raise ValueError('Only shared demographic fields may be updated')
        name=d.get('name',identity['name']);dob=d.get('dob',identity['dob']);phone=d.get('phone',identity['phone'])
        if not isinstance(name,str) or not name.strip() or len(name)>200 or not isinstance(phone,str) or len(phone)>100:raise ValueError('Valid patient name and phone required')
        date.fromisoformat(dob)
        if d.get('version')!=identity['version']:handler.send(409,{'error':'Shared profile changed; search again before updating'});return True
        c.execute('INSERT INTO mobility_profile_history(identity_id,version,name,dob,phone,actor,hospital_id) VALUES(?,?,?,?,?,?,?)',(iid,identity['version'],identity['name'],identity['dob'],identity['phone'],u['username'],hid))
        c.execute('UPDATE mobility_identities SET name=?,dob=?,phone=?,version=version+1,updated_by=?,updated_hospital_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(name.strip(),dob,phone,u['username'],hid,iid))
        handler.audit(c,u,'mobility-profile-update','patient-identity',iid);handler.send(200,{'ok':True});return True
    raise ValueError('Unknown portability action')
