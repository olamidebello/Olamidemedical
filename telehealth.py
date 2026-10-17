"""Two-party visits with authenticated signaling, chat and consent."""
import base64
from datetime import datetime
import hashlib
import hmac
import json
import os
import time


def initialize(c):
    for sql in [
      '''CREATE TABLE IF NOT EXISTS telemedicine_visits(id INTEGER PRIMARY KEY,hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
        patient_id INTEGER NOT NULL REFERENCES patients(id),provider_id INTEGER NOT NULL REFERENCES users(id),scheduled_at TEXT NOT NULL,
        reason TEXT NOT NULL,mode TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'scheduled',consent_reference TEXT,
        consent_by TEXT,version INTEGER NOT NULL DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
      '''CREATE TABLE IF NOT EXISTS telemedicine_events(id INTEGER PRIMARY KEY,visit_id INTEGER REFERENCES telemedicine_visits(id),
        user_id INTEGER REFERENCES users(id),kind TEXT NOT NULL,payload TEXT NOT NULL,created_at INTEGER NOT NULL)''',
      'CREATE INDEX IF NOT EXISTS telemedicine_visit_tenant ON telemedicine_visits(hospital_id,id)',
      'CREATE INDEX IF NOT EXISTS telemedicine_events_visit ON telemedicine_events(visit_id,id)'
    ]:c.execute(sql)


def ice_servers(uid):
    urls=[url for url in os.environ.get('MEDICAL_TURN_URLS','').split(',') if url.startswith(('turn:','turns:'))]
    secret=os.environ.get('MEDICAL_TURN_SECRET','')
    if not urls or not secret:return []
    username=str(int(time.time())+3600)+':'+str(uid)
    credential=base64.b64encode(hmac.new(secret.encode(),username.encode(),hashlib.sha1).digest()).decode()
    return [{'urls':urls,'username':username,'credential':credential}]


def handle(handler,c,u,path,method):
    if path not in ('/api/telemedicine','/api/telemedicine-providers','/api/telemedicine-events'):return False
    if u['role'] not in ('admin','clinician','nurse','reception','patient'):handler.send(403,{'error':'Visit access required'});return True
    hid=u['hospital_id']
    if path=='/api/telemedicine-providers':
        if method!='GET':handler.send(405,{'error':'Read only'})
        else:handler.send(200,[dict(r) for r in c.execute("SELECT id,username,role FROM users WHERE hospital_id=? AND active=1 AND role IN ('clinician','nurse') ORDER BY username",(hid,))])
        return True
    if path=='/api/telemedicine' and method=='GET':
        where='hospital_id=?';params=[hid]
        if u['role']=='patient':where+=' AND patient_id=?';params.append(u['patient_id'])
        elif u['role'] in ('clinician','nurse'):where+=' AND provider_id=?';params.append(u['id'])
        handler.send(200,[dict(r) for r in c.execute('SELECT * FROM telemedicine_visits WHERE '+where+' ORDER BY scheduled_at DESC LIMIT 500',params)]);return True
    if method=='GET':
        from urllib.parse import urlparse,parse_qs
        query=parse_qs(urlparse(handler.path).query);d={k:v[0] for k,v in query.items()}
    else:d=handler.body();c.execute('BEGIN IMMEDIATE')
    if path=='/api/telemedicine' and method=='POST':
        if set(d)-{'patient_id','provider_id','scheduled_at','reason','mode'}:raise ValueError('Unknown visit field')
        pid=u['patient_id'] if u['role']=='patient' else d.get('patient_id')
        if not c.execute('SELECT 1 FROM patients WHERE id=? AND hospital_id=?',(pid,hid)).fetchone():raise ValueError('Local patient required')
        provider=c.execute("SELECT * FROM users WHERE id=? AND hospital_id=? AND active=1 AND role IN ('clinician','nurse')",(d.get('provider_id'),hid)).fetchone()
        if not provider:raise ValueError('Active local doctor/nurse account required')
        if u['role'] in ('clinician','nurse') and provider['id']!=u['id']:raise ValueError('Schedule your own visit or ask reception')
        stamp=datetime.fromisoformat(d.get('scheduled_at','').replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('Timezone-aware appointment time required')
        if d.get('mode') not in ('video','audio','chat') or not isinstance(d.get('reason'),str) or not 1<=len(d['reason'])<=2000:raise ValueError('Visit reason and video/audio/chat mode required')
        if c.execute("SELECT 1 FROM telemedicine_visits WHERE hospital_id=? AND provider_id=? AND julianday(scheduled_at)=julianday(?) AND status NOT IN ('cancelled','completed')",(hid,provider['id'],d['scheduled_at'])).fetchone():raise ValueError('Provider is already scheduled at this time')
        cur=c.execute('INSERT INTO telemedicine_visits(hospital_id,patient_id,provider_id,scheduled_at,reason,mode) VALUES(?,?,?,?,?,?)',(hid,pid,provider['id'],stamp.isoformat(),d['reason'],d['mode']))
        handler.audit(c,u,'telemedicine-schedule','visit',cur.lastrowid);handler.send(200,{'id':cur.lastrowid});return True
    visit=c.execute('SELECT * FROM telemedicine_visits WHERE id=? AND hospital_id=?',(d.get('visit_id',d.get('id')),hid)).fetchone()
    if not visit or (u['role']=='patient' and visit['patient_id']!=u['patient_id']) or (u['role'] in ('clinician','nurse') and visit['provider_id']!=u['id']):handler.send(404,{'error':'Visit not found'});return True
    participant=(u['role']=='patient' and visit['patient_id']==u['patient_id']) or visit['provider_id']==u['id']
    if path=='/api/telemedicine' and method=='PATCH':
        action=d.get('action')
        if action=='consent':
            if not participant and u['role']!='admin':handler.send(403,{'error':'Participant consent required'});return True
            reference=d.get('consent_reference')
            if not isinstance(reference,str) or not 3<=len(reference)<=500:raise ValueError('Record patient consent or its authorization reference')
            c.execute('UPDATE telemedicine_visits SET consent_reference=?,consent_by=?,version=version+1 WHERE id=?',(reference,u['username'],visit['id']))
        elif action=='status':
            transitions={'scheduled':{'waiting','cancelled'},'waiting':{'in-progress','cancelled'},'in-progress':{'completed','cancelled'},'completed':set(),'cancelled':set()}
            state=d.get('status')
            if state not in transitions[visit['status']]:raise ValueError('Invalid visit transition')
            if u['role']=='patient' and state not in ('waiting','cancelled'):raise ValueError('Clinician completes the consultation')
            if state=='in-progress' and not visit['consent_reference']:raise ValueError('Patient consent required before starting')
            cur=c.execute('UPDATE telemedicine_visits SET status=?,version=version+1 WHERE id=? AND version=?',(state,visit['id'],d.get('version')))
            if not cur.rowcount:handler.send(409,{'error':'Visit changed; refresh and retry'});return True
            if state in ('completed','cancelled'):c.execute("DELETE FROM telemedicine_events WHERE visit_id=? AND kind!='chat'",(visit['id'],))
        else:raise ValueError('Valid visit action required')
        handler.audit(c,u,'telemedicine-'+action,'visit',visit['id']);handler.send(200,{'ok':True});return True
    if path=='/api/telemedicine-events':
        if not participant:handler.send(403,{'error':'Only assigned participants may access consultation media/chat'});return True
        if visit['status'] not in ('waiting','in-progress') or not visit['consent_reference']:raise ValueError('Active visit and recorded consent required')
        if method=='GET':
            since=int(d.get('since',0));events=[]
            for r in c.execute('SELECT * FROM telemedicine_events WHERE visit_id=? AND id>? AND created_at>? ORDER BY id LIMIT 200',(visit['id'],since,int(time.time())-86400)):
                events.append({**dict(r),'payload':json.loads(r['payload'])})
            handler.send(200,{'events':events,'ice_servers':ice_servers(u['id']),'relay_configured':bool(ice_servers(u['id']))});return True
        if method=='POST':
            kind=d.get('kind');payload=d.get('payload')
            if kind not in ('offer','answer','candidate','chat','leave'):raise ValueError('Unsupported consultation event')
            if kind=='offer' and visit['provider_id']!=u['id']:raise ValueError('Assigned clinician initiates the media offer')
            if kind=='answer' and u['role']!='patient':raise ValueError('Patient answers the media offer')
            if kind=='chat' and (not isinstance(payload,str) or not 1<=len(payload)<=4000):raise ValueError('Chat message must contain 1–4000 characters')
            if kind in ('offer','answer','candidate') and not isinstance(payload,dict):raise ValueError('Structured signaling payload required')
            if len(json.dumps(payload))>50000:raise ValueError('Signaling payload too large')
            count=c.execute('SELECT COUNT(*) FROM telemedicine_events WHERE visit_id=? AND created_at>?',(visit['id'],int(time.time())-60)).fetchone()[0]
            if count>=240:handler.send(429,{'error':'Consultation event rate limit reached'});return True
            c.execute('INSERT INTO telemedicine_events(visit_id,user_id,kind,payload,created_at) VALUES(?,?,?,?,?)',(visit['id'],u['id'],kind,json.dumps(payload),int(time.time())))
            handler.audit(c,u,'telemedicine-event','visit',visit['id']);handler.send(200,{'ok':True});return True
    handler.send(405,{'error':'Unsupported visit action'});return True
