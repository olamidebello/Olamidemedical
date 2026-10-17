"""Hospital-owned provider applications, review and registry lifecycle."""
from datetime import date
import time
import registration

ROLES={'doctor':'clinician','nurse':'nurse','pharmacist':'pharmacist','dentist':'clinician','therapist':'clinician','allied_health':'clinician'}
ATTEMPTS={}


def initialize(c):
 c.execute('''CREATE TABLE IF NOT EXISTS provider_applications(id INTEGER PRIMARY KEY,hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
    name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,profession TEXT NOT NULL,specialty TEXT NOT NULL,
    license_number TEXT NOT NULL,license_jurisdiction TEXT NOT NULL,license_expiry TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',review_reference TEXT,reviewed_by TEXT,reviewed_at TEXT,
    professional_id INTEGER REFERENCES professionals(id),created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
 c.execute('CREATE INDEX IF NOT EXISTS provider_applications_hospital ON provider_applications(hospital_id,status)')


def public(h,c,path,method):
 if path!='/api/provider-registration':return False
 if method!='POST':h.send(405,{'error':'Use POST'});return True
 if h.headers.get('X-Requested-With')!='OlamideMedical':h.send(403,{'error':'Request verification required'});return True
 now=time.time();key=h.client_address[0];attempts=[t for t in ATTEMPTS.get(key,[]) if t>now-3600];ATTEMPTS[key]=attempts
 if len(attempts)>=10:h.send(429,{'error':'Provider registration limit reached; retry later'});return True
 attempts.append(now);d=h.body()
 fields={'hospital_slug','name','email','phone','profession','specialty','license_number','license_jurisdiction','license_expiry'}
 if set(d)!=fields:raise ValueError('Complete the provider registration fields')
 values={key:registration.text(d,key,200) for key in fields if key not in ('email','profession','license_expiry')}
 mail=registration.email(d['email']);profession=d['profession']
 if profession not in ROLES:raise ValueError('Supported provider profession required')
 if date.fromisoformat(d['license_expiry'])<date.today():raise ValueError('A current license expiry date is required')
 hospital=c.execute('SELECT id FROM hospitals WHERE slug=? AND active=1',(values['hospital_slug'],)).fetchone()
 if not hospital:raise ValueError('Active hospital/practice registration code required')
 c.execute('BEGIN IMMEDIATE')
 if c.execute("SELECT 1 FROM provider_applications WHERE hospital_id=? AND lower(email)=lower(?) AND status='pending'",(hospital['id'],mail)).fetchone():raise ValueError('A pending application already exists for this email at this hospital')
 c.execute('''INSERT INTO provider_applications(hospital_id,name,email,phone,profession,specialty,license_number,license_jurisdiction,license_expiry)
   VALUES(?,?,?,?,?,?,?,?,?)''',(hospital['id'],values['name'],mail,values['phone'],profession,values['specialty'],values['license_number'],values['license_jurisdiction'],d['license_expiry']))
 h.send(202,{'message':'Provider application submitted for hospital review. No clinical account or access has been activated.'});return True


def handle(h,c,u,path,method):
 if path not in ('/api/provider-applications','/api/provider-management'):return False
 if u['role']!='admin':h.send(403,{'error':'Hospital administrator required'});return True
 hid=u['hospital_id']
 if path=='/api/provider-applications':
  if method=='GET':h.send(200,[dict(r) for r in c.execute('SELECT * FROM provider_applications WHERE hospital_id=? ORDER BY id DESC LIMIT 500',(hid,))]);return True
  if method!='POST':h.send(405,{'error':'Use POST'});return True
  d=h.body();c.execute('BEGIN IMMEDIATE')
  if set(d)-{'id','action','review_reference'}:raise ValueError('Unknown application review field')
  app=c.execute("SELECT * FROM provider_applications WHERE id=? AND hospital_id=? AND status='pending'",(d.get('id'),hid)).fetchone()
  if not app:h.send(409,{'error':'Pending local application not found'});return True
  reference=registration.text(d,'review_reference',1000)
  if d.get('action') not in ('approve','reject'):raise ValueError('Approve or reject the application')
  profile_id=None;response={'ok':True}
  if d['action']=='approve':
   if date.fromisoformat(app['license_expiry'])<date.today():raise ValueError('License has expired; request updated credentials before approval')
   if c.execute("SELECT 1 FROM professionals WHERE hospital_id=? AND license_number=? AND license_jurisdiction=? AND status!='suspended'",(hid,app['license_number'],app['license_jurisdiction'])).fetchone():raise ValueError('Provider license already exists in this hospital registry')
   profile_id=c.execute('''INSERT INTO professionals(hospital_id,name,email,phone,profession,specialty,license_number,license_jurisdiction,license_expiry,credential_status,credential_reference,status,created_by)
      VALUES(?,?,?,?,?,?,?,?,?,'reviewed',?,'inactive',?)''',(hid,app['name'],app['email'],app['phone'],app['profession'],app['specialty'],app['license_number'],app['license_jurisdiction'],app['license_expiry'],reference,u['username'])).lastrowid
   response=registration.invite(c,hid,ROLES[app['profession']],None,None,u['username'],professional_id=profile_id)
   response.update({'professional_id':profile_id,'message':'Approved. Deliver this invitation privately; the provider remains inactive until account registration and explicit activation.'})
  c.execute('UPDATE provider_applications SET status=?,review_reference=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP,professional_id=? WHERE id=?',('approved' if profile_id else 'rejected',reference,u['username'],profile_id,app['id']))
  h.audit(c,u,'provider-application-'+d['action'],'provider-application',app['id']);h.send(200,response);return True
 if method!='PATCH':h.send(405,{'error':'Use PATCH'});return True
 d=h.body();c.execute('BEGIN IMMEDIATE')
 if set(d)-{'id','action','version','review_reference'}:raise ValueError('Unknown provider action field')
 profile=c.execute('SELECT * FROM professionals WHERE id=? AND hospital_id=?',(d.get('id'),hid)).fetchone()
 if not profile:h.send(404,{'error':'Local provider not found'});return True
 if d.get('version')!=profile['version']:h.send(409,{'error':'Provider changed; refresh and retry'});return True
 action=d.get('action')
 if action=='activate':
  if profile['credential_status']!='reviewed' or not profile['credential_reference'] or not profile['license_expiry'] or date.fromisoformat(profile['license_expiry'])<date.today():raise ValueError('Reviewed current credentials and a review reference required')
  account=c.execute('SELECT * FROM users WHERE id=? AND hospital_id=?',(profile['user_id'],hid)).fetchone()
  if not account or account['role']!=ROLES[profile['profession']]:raise ValueError('Provider must register a matching staff account before activation')
  c.execute('UPDATE users SET active=1 WHERE id=? AND hospital_id=?',(account['id'],hid))
  c.execute("UPDATE professionals SET status='active',version=version+1 WHERE id=?",(profile['id'],))
 elif action=='invite':
  response=registration.invite(c,hid,ROLES[profile['profession']],None,None,u['username'],professional_id=profile['id'])
  h.audit(c,u,'provider-invite','professional',profile['id']);h.send(200,response);return True
 elif action in ('suspend','deactivate'):
  if profile['user_id']:
   linked=c.execute('SELECT role FROM users WHERE id=? AND hospital_id=?',(profile['user_id'],hid)).fetchone()
   if not linked or linked['role']!=ROLES[profile['profession']]:raise ValueError('Linked account role changed; review it in Staff & access before disabling provider access')
  c.execute('UPDATE professionals SET status=?,version=version+1 WHERE id=?',('suspended' if action=='suspend' else 'inactive',profile['id']))
  if profile['user_id']:
   c.execute('UPDATE users SET active=0 WHERE id=? AND hospital_id=?',(profile['user_id'],hid));c.execute('DELETE FROM sessions WHERE user_id=?',(profile['user_id'],))
 elif action=='review':
  reference=registration.text(d,'review_reference',1000)
  if not profile['license_number'] or not profile['license_jurisdiction'] or not profile['license_expiry'] or date.fromisoformat(profile['license_expiry'])<date.today():raise ValueError('Record current license details before credential review')
  c.execute("UPDATE professionals SET credential_status='reviewed',credential_reference=?,version=version+1 WHERE id=?",(reference,profile['id']))
 else:raise ValueError('Activate, deactivate, suspend or review provider credentials')
 h.audit(c,u,'provider-'+action,'professional',profile['id']);h.send(200,{'ok':True});return True
