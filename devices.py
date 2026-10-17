"""Tenant-bound device telemetry. Readings require clinical review before chart posting."""
from datetime import datetime, timezone
import hashlib
import json
import math
import secrets

# Canonical UCUM units; no implicit clinical unit conversions.
VITALS={'8310-5':('temperature','Cel'),'8867-4':('pulse','/min'),
        '8480-6':('systolic','mm[Hg]'),'8462-4':('diastolic','mm[Hg]'),
        '59408-5':('oxygen','%'),'29463-7':('weight','kg')}


def initialize(c):
    for sql in [
      '''CREATE TABLE IF NOT EXISTS medical_devices(id INTEGER PRIMARY KEY,hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
        name TEXT NOT NULL,manufacturer TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',protocol TEXT NOT NULL,
        token_hash TEXT UNIQUE NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,last_seen TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
      '''CREATE TABLE IF NOT EXISTS device_readings(id INTEGER PRIMARY KEY,hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
        device_id INTEGER NOT NULL REFERENCES medical_devices(id),patient_id INTEGER NOT NULL REFERENCES patients(id),
        message_id TEXT NOT NULL,code TEXT NOT NULL,value REAL NOT NULL,unit TEXT NOT NULL,observed_at TEXT NOT NULL,
        payload_hash TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',reviewed_by TEXT,vital_id INTEGER REFERENCES vitals(id),
        received_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(device_id,message_id))''',
      '''CREATE TRIGGER IF NOT EXISTS device_reading_guard BEFORE INSERT ON device_readings BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM medical_devices WHERE id=NEW.device_id AND hospital_id=NEW.hospital_id)
        OR NOT EXISTS(SELECT 1 FROM patients WHERE id=NEW.patient_id AND hospital_id=NEW.hospital_id)
        THEN RAISE(ABORT,'Device/patient hospital mismatch') END; END''',
      'CREATE INDEX IF NOT EXISTS device_readings_hospital ON device_readings(hospital_id,id)'
    ]:c.execute(sql)


def token_hash(token):return hashlib.sha256(token.encode()).hexdigest()


def normalize(d):
    if d.get('resourceType')=='Observation':
        codings=d.get('code',{}).get('coding',[])
        code=next((x['code'] for x in codings if x.get('system')=='http://loinc.org'),None)
        subject=d.get('subject',{}).get('reference','')
        if not subject.startswith('Patient/') or not subject[8:].isdigit():raise ValueError('FHIR subject must reference a local Patient/<numeric-id>')
        quantity=d.get('valueQuantity',{})
        if quantity.get('system')!='http://unitsofmeasure.org':raise ValueError('FHIR quantity requires UCUM system and code')
        if d.get('status') not in ('final','amended','corrected'):raise ValueError('Only final/amended/corrected FHIR observations accepted')
        d={'patient_id':int(subject[8:]),'message_id':d.get('id'),'code':code,'value':quantity.get('value'),'unit':quantity.get('code'),'observed_at':d.get('effectiveDateTime')}
    required={'patient_id','message_id','code','value','unit','observed_at'}
    if set(d)!=required:raise ValueError('Supply patient_id, message_id, code, value, unit and observed_at only')
    for field,limit in [('message_id',150),('code',80),('unit',40)]:
        if not isinstance(d[field],str) or not d[field] or len(d[field])>limit:raise ValueError('Invalid '+field)
    if not isinstance(d['patient_id'],int) or isinstance(d['patient_id'],bool) or d['patient_id']<=0:raise ValueError('Local numeric patient ID required')
    if isinstance(d['value'],bool) or not isinstance(d['value'],(int,float)) or not math.isfinite(d['value']):raise ValueError('Finite numeric reading required')
    if not isinstance(d['observed_at'],str):raise ValueError('Timezone-aware observed_at required')
    stamp=datetime.fromisoformat(d['observed_at'].replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('Timezone-aware observed_at required')
    d['observed_at']=stamp.astimezone(timezone.utc).isoformat()
    return d


def ingest(handler,c):
    auth=handler.headers.get('Authorization','')
    if not auth.startswith('Bearer ') or len(auth)>300:handler.send(401,{'error':'Device bearer token required'});return
    device=c.execute('''SELECT d.* FROM medical_devices d JOIN hospitals h ON h.id=d.hospital_id
      WHERE token_hash=? AND d.enabled=1 AND h.active=1''',(token_hash(auth[7:]),)).fetchone()
    if not device:handler.send(401,{'error':'Invalid or disabled device'});return
    raw=handler.body()
    if device['protocol']=='fhir-observation' and raw.get('resourceType')!='Observation':raise ValueError('Registered device requires a FHIR Observation')
    if device['protocol']=='normalized-json' and 'resourceType' in raw:raise ValueError('Registered device requires normalized JSON')
    d=normalize(raw);hid=device['hospital_id'];c.execute('BEGIN IMMEDIATE')
    if not c.execute('SELECT 1 FROM patients WHERE id=? AND hospital_id=?',(d['patient_id'],hid)).fetchone():raise ValueError('Patient is not registered at this device hospital')
    digest=token_hash(json.dumps(d,sort_keys=True,separators=(',',':')))
    old=c.execute('SELECT id,payload_hash FROM device_readings WHERE device_id=? AND message_id=?',(device['id'],d['message_id'])).fetchone()
    if old:
        if old['payload_hash']!=digest:handler.send(409,{'error':'Message ID already used for a different reading'});return
        handler.send(200,{'id':old['id'],'duplicate':True});return
    cur=c.execute('''INSERT INTO device_readings(hospital_id,device_id,patient_id,message_id,code,value,unit,observed_at,payload_hash)
      VALUES(?,?,?,?,?,?,?,?,?)''',(hid,device['id'],d['patient_id'],d['message_id'],d['code'],d['value'],d['unit'],d['observed_at'],digest))
    c.execute('UPDATE medical_devices SET last_seen=CURRENT_TIMESTAMP WHERE id=?',(device['id'],))
    c.execute("INSERT INTO audit(actor,action,resource,record_id,hospital_id) VALUES(?,'device-ingest','device-reading',?,?)",('device:'+str(device['id']),cur.lastrowid,hid))
    c.execute("INSERT INTO alerts(hospital_id,title,message,severity,audience,status,created_by) VALUES(?,?,?,'info','clinical','open',?)",(hid,'Device reading pending review','Open Medical devices to review measurement '+str(cur.lastrowid),'device:'+str(device['id'])))
    handler.send(202,{'id':cur.lastrowid,'status':'pending','duplicate':False})


def handle(handler,c,u,path,method):
    if path not in ('/api/devices','/api/device-readings','/api/device-review'):return False
    if u['role'] not in ('admin','clinician','nurse'):handler.send(403,{'error':'Hospital clinical access required'});return True
    hid=u['hospital_id']
    if path=='/api/device-readings':
        if method!='GET':handler.send(405,{'error':'Read only; use review actions'})
        else:handler.send(200,[dict(r) for r in c.execute('''SELECT r.id,r.device_id,d.name AS device,r.patient_id,r.message_id,r.code,r.value,r.unit,r.observed_at,r.status,r.reviewed_by,r.vital_id,r.received_at
           FROM device_readings r JOIN medical_devices d ON d.id=r.device_id WHERE r.hospital_id=? ORDER BY r.id DESC LIMIT 500''',(hid,))])
        return True
    if path=='/api/devices' and method=='GET':
        handler.send(200,[dict(r) for r in c.execute('SELECT id,hospital_id,name,manufacturer,model,protocol,enabled,last_seen FROM medical_devices WHERE hospital_id=? ORDER BY name',(hid,))]);return True
    if path=='/api/devices' and u['role']!='admin':handler.send(403,{'error':'Hospital administrator required'});return True
    d=handler.body();c.execute('BEGIN IMMEDIATE')
    if path=='/api/devices':
        if method=='POST':
            if set(d)-{'name','manufacturer','model','protocol'}:raise ValueError('Unknown device field')
            if not isinstance(d.get('name'),str) or not 1<=len(d['name'].strip())<=150:raise ValueError('Device name required')
            if d.get('protocol') not in ('normalized-json','fhir-observation'):raise ValueError('Supported protocol required')
            token=secrets.token_urlsafe(40)
            cur=c.execute('INSERT INTO medical_devices(hospital_id,name,manufacturer,model,protocol,token_hash) VALUES(?,?,?,?,?,?)',(hid,d['name'].strip(),str(d.get('manufacturer',''))[:150],str(d.get('model',''))[:150],d['protocol'],token_hash(token)))
            handler.audit(c,u,'device-register','medical-device',cur.lastrowid);handler.send(200,{'id':cur.lastrowid,'token':token});return True
        if method=='PATCH':
            device=c.execute('SELECT * FROM medical_devices WHERE id=? AND hospital_id=?',(d.get('id'),hid)).fetchone()
            if not device:handler.send(404,{'error':'Device not found'});return True
            if d.get('action')=='rotate':
                token=secrets.token_urlsafe(40);c.execute('UPDATE medical_devices SET token_hash=? WHERE id=?',(token_hash(token),device['id']))
                handler.audit(c,u,'device-token-rotate','medical-device',device['id']);handler.send(200,{'token':token});return True
            if set(d)!={'id','enabled'} or not isinstance(d['enabled'],bool):raise ValueError('Boolean enabled state required')
            c.execute('UPDATE medical_devices SET enabled=? WHERE id=?',(int(d['enabled']),device['id']))
            handler.audit(c,u,'device-status','medical-device',device['id']);handler.send(200,{'ok':True});return True
    if path=='/api/device-review' and method=='POST':
        if set(d)!={'id','action'} or d['action'] not in ('accept','reject'):raise ValueError('Review action must be accept or reject')
        r=c.execute("SELECT * FROM device_readings WHERE id=? AND hospital_id=? AND status='pending'",(d['id'],hid)).fetchone()
        if not r:handler.send(409,{'error':'Pending reading not found; refresh before review'});return True
        vital=None
        if d['action']=='accept':
            mapping=VITALS.get(r['code'])
            if not mapping or mapping[1]!=r['unit']:raise ValueError('No approved vital/unit mapping; retain as telemetry or reject. No automatic conversion is performed.')
            field=mapping[0]
            vital=c.execute(f'INSERT INTO vitals(hospital_id,patient_id,{field},created_by) VALUES(?,?,?,?)',(hid,r['patient_id'],r['value'],u['username'])).lastrowid
        c.execute('UPDATE device_readings SET status=?,reviewed_by=?,vital_id=? WHERE id=?',('accepted' if vital else 'rejected',u['username'],vital,r['id']))
        handler.audit(c,u,'device-review-'+d['action'],'device-reading',r['id']);handler.send(200,{'ok':True,'vital_id':vital});return True
    handler.send(405,{'error':'Unsupported device action'});return True
