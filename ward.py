"""Hospital charting, duty scheduling, attendance and coverage workflows."""
from datetime import datetime,timezone,timedelta
import json
import clinical_ai

NURSING={
 'shift_assessment':['condition','symptoms','observations','changes'],
 'vital_signs':['temperature','blood_pressure','pulse','respiratory_rate','oxygen_saturation'],
 'pain_assessment':['score','location','intervention','reassessment'],
 'medication_administration':['medication','dose','route','administered_at','omissions','reactions'],
 'intake_output':['oral_fluids','iv_fluids','urine','drains','other_losses','units'],
 'nursing_care_plan':['problems','goals','interventions','outcomes'],
 'wound_skin':['location','observations','dressing_changes','skin_condition'],
 'devices_lines':['device_type','site','observations','care_performed'],
 'mobility_safety':['assistance','falls_precautions','safety_observations'],
 'patient_education':['teaching','patient_understanding'],
 'nursing_progress':['care_delivered','patient_response','concerns_escalated'],
 'nursing_handover':['condition','outstanding_tasks','pending_results','receiving_staff'],
 'nursing_discharge_transfer':['instructions','condition','destination','receiving_staff']}
DOCTOR={
 'admission_assessment':['presenting_complaint','history','examination','initial_plan'],
 'daily_progress':['symptoms','findings','assessment','treatment_plan'],
 'problem_list':['active_diagnoses','problem_status'],
 'medical_orders':['medications','tests','procedures','monitoring','referrals'],
 'results_review':['findings_reviewed','interpretation','actions_taken'],
 'consultation_note':['specialist_assessment','recommendations'],
 'procedure_note':['procedure','consent','findings','complications','follow_up'],
 'treatment_review':['response','changes_to_plan'],
 'discharge_summary':['hospital_course','diagnoses','medications','follow_up'],
 'clinical_handover':['patient_risks','pending_work','responsibility_transferred']}
TEMPLATES={**NURSING,**DOCTOR}


def initialize(c):
 for sql in [
  '''CREATE TABLE IF NOT EXISTS clinical_entries(id INTEGER PRIMARY KEY,hospital_id INTEGER REFERENCES hospitals(id),patient_id INTEGER REFERENCES patients(id),
     author_id INTEGER REFERENCES users(id),entry_type TEXT NOT NULL,fields TEXT NOT NULL,care_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',
     signed_at TEXT,correction_of INTEGER REFERENCES clinical_entries(id),correction_reason TEXT,version INTEGER NOT NULL DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
  '''CREATE TABLE IF NOT EXISTS duty_shifts(id INTEGER PRIMARY KEY,hospital_id INTEGER REFERENCES hospitals(id),staff_id INTEGER REFERENCES users(id),
     department TEXT NOT NULL,shift_name TEXT NOT NULL,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,responsibility TEXT,on_call TEXT NOT NULL DEFAULT 'none',
     supervisor_id INTEGER REFERENCES users(id),covering_id INTEGER REFERENCES users(id),attendance TEXT NOT NULL DEFAULT 'scheduled',handover TEXT NOT NULL DEFAULT 'pending',
     handover_entry_id INTEGER REFERENCES clinical_entries(id),clocked_in_at TEXT,clocked_out_at TEXT,replacement_for_id INTEGER,version INTEGER NOT NULL DEFAULT 1)''',
  '''CREATE TABLE IF NOT EXISTS shift_patients(shift_id INTEGER REFERENCES duty_shifts(id),patient_id INTEGER REFERENCES patients(id),hospital_id INTEGER REFERENCES hospitals(id),PRIMARY KEY(shift_id,patient_id))''',
  '''CREATE TABLE IF NOT EXISTS staff_leave(id INTEGER PRIMARY KEY,hospital_id INTEGER REFERENCES hospitals(id),staff_id INTEGER REFERENCES users(id),starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,
     reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',reviewed_by INTEGER REFERENCES users(id))''',
  '''CREATE TABLE IF NOT EXISTS shift_swaps(id INTEGER PRIMARY KEY,hospital_id INTEGER REFERENCES hospitals(id),shift_id INTEGER REFERENCES duty_shifts(id),target_shift_id INTEGER REFERENCES duty_shifts(id),
     requester_id INTEGER REFERENCES users(id),target_id INTEGER REFERENCES users(id),shift_version INTEGER,target_version INTEGER,status TEXT NOT NULL DEFAULT 'requested',reviewed_by INTEGER REFERENCES users(id))''',
  '''CREATE TRIGGER IF NOT EXISTS signed_entry_immutable BEFORE UPDATE ON clinical_entries WHEN OLD.status='signed' BEGIN SELECT RAISE(ABORT,'Signed entry is immutable'); END''',
  '''CREATE TRIGGER IF NOT EXISTS signed_entry_no_delete BEFORE DELETE ON clinical_entries WHEN OLD.status='signed' BEGIN SELECT RAISE(ABORT,'Signed entry is immutable'); END''',
  '''CREATE TRIGGER IF NOT EXISTS entry_hospital_guard BEFORE INSERT ON clinical_entries BEGIN
     SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM patients WHERE id=NEW.patient_id AND hospital_id=NEW.hospital_id)
     OR NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.author_id AND hospital_id=NEW.hospital_id)
     THEN RAISE(ABORT,'Chart tenant mismatch') END; END''',
  'CREATE INDEX IF NOT EXISTS clinical_entries_patient ON clinical_entries(hospital_id,patient_id,id)',
  'CREATE INDEX IF NOT EXISTS duty_shifts_tenant ON duty_shifts(hospital_id,staff_id,starts_at)'
 ]:c.execute(sql)


def stamp(value):
 if not isinstance(value,str):raise ValueError('Timezone-aware time required')
 dt=datetime.fromisoformat(value.replace('Z','+00:00'))
 if dt.tzinfo is None:raise ValueError('Include timezone in all care and roster times')
 return dt.astimezone(timezone.utc).isoformat()


def staff(c,uid,hid):
 row=c.execute("SELECT id,username,role FROM users WHERE id=? AND hospital_id=? AND active=1 AND role IN ('clinician','nurse')",(uid,hid)).fetchone()
 if not row:raise ValueError('Active local doctor or nurse account required')
 return row


def available(c,uid,hid,start,end,exclude=()):
 placeholders=','.join('?' for _ in exclude) or '0'
 if c.execute(f"SELECT 1 FROM duty_shifts WHERE hospital_id=? AND staff_id=? AND attendance NOT IN ('absent','replaced') AND starts_at<? AND ends_at>? AND id NOT IN ({placeholders})",(hid,uid,end,start,*exclude)).fetchone():return False
 if c.execute("SELECT 1 FROM staff_leave WHERE hospital_id=? AND staff_id=? AND status='approved' AND starts_at<? AND ends_at>?",(hid,uid,end,start)).fetchone():return False
 return True


def rows(c,sql,params):return [dict(r) for r in c.execute(sql,params)]


def handle(h,c,u,path,method):
 paths=('/api/ward-config','/api/clinical-entries','/api/duty-shifts','/api/shift-patients','/api/staff-leave','/api/shift-swaps','/api/coverage','/api/ward-ai','/api/swap-options')
 if path not in paths:return False
 if u['role'] not in ('admin','clinician','nurse'):h.send(403,{'error':'Hospital care-team access required'});return True
 hid=u['hospital_id'];admin=u['role']=='admin'
 from urllib.parse import urlparse,parse_qs
 q=parse_qs(urlparse(h.path).query)
 if path=='/api/ward-config':
  if method!='GET':h.send(405,{'error':'Read only'});return True
  templates=TEMPLATES if admin else NURSING if u['role']=='nurse' else DOCTOR
  h.send(200,{'templates':templates,'staff':rows(c,"SELECT id,username,role FROM users WHERE hospital_id=? AND active=1 AND role IN ('clinician','nurse') ORDER BY username",(hid,))});return True
 if path=='/api/clinical-entries' and method=='GET':
  where='e.hospital_id=?';params=[hid]
  if q.get('patient_id'):where+=' AND e.patient_id=?';params.append(int(q['patient_id'][0]))
  # Staff see signed entries and their own drafts; administrators see metadata/content locally.
  if not admin:where+=" AND (e.status='signed' OR e.author_id=?)";params.append(u['id'])
  result=rows(c,'SELECT e.*,u.username AS author FROM clinical_entries e JOIN users u ON u.id=e.author_id WHERE '+where+' ORDER BY e.care_at DESC LIMIT 500',params)
  for row in result:row['fields']=json.loads(row['fields'])
  h.audit(c,u,'read','clinical-entry');h.send(200,result);return True
 if path=='/api/duty-shifts' and method=='GET':
  where='s.hospital_id=?';params=[hid]
  if not admin:where+=' AND (s.staff_id=? OR s.supervisor_id=?)';params.extend([u['id'],u['id']])
  if q.get('from'):where+=' AND s.ends_at>=?';params.append(stamp(q['from'][0]))
  if q.get('to'):where+=' AND s.starts_at<=?';params.append(stamp(q['to'][0]))
  result=rows(c,'SELECT s.*,u.username AS staff,u.role FROM duty_shifts s JOIN users u ON u.id=s.staff_id WHERE '+where+' ORDER BY s.starts_at LIMIT 500',params)
  for row in result:row['patients']=rows(c,'SELECT p.id,p.name FROM shift_patients sp JOIN patients p ON p.id=sp.patient_id WHERE sp.shift_id=? AND sp.hospital_id=?',(row['id'],hid))
  h.send(200,result);return True
 if path in ('/api/staff-leave','/api/shift-swaps') and method=='GET':
  table='staff_leave' if path.endswith('staff-leave') else 'shift_swaps'
  where='hospital_id=?';params=[hid]
  if not admin:
   where+=' AND staff_id=?' if table=='staff_leave' else ' AND (requester_id=? OR target_id=?)';params.extend([u['id']] if table=='staff_leave' else [u['id'],u['id']])
  h.send(200,rows(c,f'SELECT * FROM {table} WHERE '+where+' ORDER BY id DESC LIMIT 500',params));return True
 if path=='/api/swap-options' and method=='GET':
  own=c.execute("SELECT * FROM duty_shifts WHERE id=? AND hospital_id=? AND staff_id=? AND attendance='scheduled'",(int(q.get('shift_id',['0'])[0]),hid,u['id'])).fetchone()
  if not own:h.send(404,{'error':'Own scheduled shift required'});return True
  role=staff(c,u['id'],hid)['role']
  h.send(200,rows(c,"SELECT s.id,s.department,s.shift_name,s.starts_at,s.ends_at,u.username FROM duty_shifts s JOIN users u ON u.id=s.staff_id WHERE s.hospital_id=? AND s.staff_id!=? AND s.attendance='scheduled' AND u.role=? AND u.active=1 ORDER BY s.starts_at LIMIT 200",(hid,u['id'],role)));return True
 if path=='/api/coverage' and method=='GET':
  if not admin:h.send(403,{'error':'Hospital administrator required'});return True
  now=datetime.now(timezone.utc).isoformat()
  active=rows(c,"SELECT s.*,u.username,u.role FROM duty_shifts s JOIN users u ON u.id=s.staff_id WHERE s.hospital_id=? AND s.starts_at<=? AND s.ends_at>? AND s.attendance NOT IN ('absent','replaced')",(hid,now,now))
  unassigned=rows(c,"SELECT DISTINCT p.id,p.name FROM patients p JOIN encounters e ON e.patient_id=p.id AND e.hospital_id=p.hospital_id WHERE p.hospital_id=? AND e.status='open' AND NOT EXISTS(SELECT 1 FROM shift_patients sp JOIN duty_shifts s ON s.id=sp.shift_id WHERE sp.patient_id=p.id AND s.hospital_id=p.hospital_id AND s.starts_at<=? AND s.ends_at>? AND s.attendance NOT IN ('absent','replaced'))",(hid,now,now))
  overlaps=rows(c,"SELECT a.id AS shift_id,b.id AS conflicting_shift,a.staff_id FROM duty_shifts a JOIN duty_shifts b ON a.staff_id=b.staff_id AND a.hospital_id=b.hospital_id AND a.id<b.id AND a.starts_at<b.ends_at AND a.ends_at>b.starts_at WHERE a.hospital_id=? AND a.attendance NOT IN ('absent','replaced') AND b.attendance NOT IN ('absent','replaced') LIMIT 500",(hid,))
  replacements=[]
  if q.get('shift_id'):
   shift=c.execute('SELECT * FROM duty_shifts WHERE id=? AND hospital_id=?',(int(q['shift_id'][0]),hid)).fetchone()
   if not shift:raise ValueError('Local shift required')
   role=staff(c,shift['staff_id'],hid)['role']
   replacements=[dict(r) for r in c.execute('SELECT id,username,role FROM users WHERE hospital_id=? AND role=? AND active=1 AND id!=?',(hid,role,shift['staff_id'])) if available(c,r['id'],hid,shift['starts_at'],shift['ends_at'])]
  h.send(200,{'active_shifts':active,'unassigned_inpatients':unassigned,'overlapping_shifts':overlaps,'pending_handovers':rows(c,"SELECT id,staff_id,ends_at FROM duty_shifts WHERE hospital_id=? AND handover='pending' AND ends_at<=? ORDER BY ends_at DESC LIMIT 500",(hid,now)),'replacements':replacements});return True
 if method not in ('POST','PATCH'):h.send(405,{'error':'Unsupported action'});return True
 d=h.body()
 if path=='/api/ward-ai':
  enabled=c.execute('SELECT ai_enabled FROM hospitals WHERE id=?',(hid,)).fetchone()[0]
  if not enabled:h.send(403,{'error':'Hospital AI permission required'});return True
  if set(d)!={'draft','confirm_no_patient_identifiers'} or d['confirm_no_patient_identifiers'] is not True:raise ValueError('Confirm de-identified draft text only')
  draft=d.get('draft')
  if not isinstance(draft,str) or not 3<=len(draft)<=4000:raise ValueError('Draft must contain 3–4000 characters')
  # Reuse the same per-user budget; never retrieve chart data for this request.
  now=__import__('time').time();key=(hid,u['id']);attempts=[t for t in clinical_ai.RATE.get(key,[]) if t>now-3600]
  if len(attempts)>=20:h.send(429,{'error':'AI hourly request limit reached'});return True
  attempts.append(now);clinical_ai.RATE[key]=attempts
  answer=clinical_ai.request_model('Organize this de-identified educational draft into headings. Preserve provided facts only; label missing information as not provided. Do not add findings, diagnoses, interventions or doses. Draft: '+draft,[])
  h.audit(c,u,'ai-draft-organization','clinical-entry');h.send(200,{'draft':answer,'review_required':True,'saved':False});return True
 c.execute('BEGIN IMMEDIATE')
 if path=='/api/clinical-entries':
  if method=='POST':
   if set(d)-{'patient_id','entry_type','fields','care_at','correction_of','correction_reason'}:raise ValueError('Unknown clinical entry field')
   templates=TEMPLATES if admin else NURSING if u['role']=='nurse' else DOCTOR
   if d.get('entry_type') not in templates:raise ValueError('Choose a chart template for your clinical role')
   pid=d.get('patient_id')
   if not c.execute('SELECT 1 FROM patients WHERE id=? AND hospital_id=?',(pid,hid)).fetchone():raise ValueError('Local patient required')
   fields=d.get('fields')
   if not isinstance(fields,dict) or set(fields)-set(templates[d['entry_type']]) or not any(isinstance(v,str) and v.strip() for v in fields.values()):raise ValueError('Record at least one real observation using the template fields')
   if any(not isinstance(v,str) or len(v)>10000 for v in fields.values()):raise ValueError('Clinical fields must be text of at most 10000 characters')
   care=stamp(d.get('care_at'))
   if datetime.fromisoformat(care)>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('Care time cannot be in the future')
   parent=d.get('correction_of');reason=d.get('correction_reason')
   if parent:
    original=c.execute("SELECT * FROM clinical_entries WHERE id=? AND hospital_id=? AND patient_id=? AND status='signed'",(parent,hid,pid)).fetchone()
    if not original or original['entry_type']!=d['entry_type'] or not isinstance(reason,str) or not 3<=len(reason)<=2000:raise ValueError('Correction requires a signed local entry of the same type and a reason')
   cur=c.execute('INSERT INTO clinical_entries(hospital_id,patient_id,author_id,entry_type,fields,care_at,correction_of,correction_reason) VALUES(?,?,?,?,?,?,?,?)',(hid,pid,u['id'],d['entry_type'],json.dumps(fields),care,parent,reason))
   h.audit(c,u,'chart-draft-create','clinical-entry',cur.lastrowid);h.send(200,{'id':cur.lastrowid});return True
  entry=c.execute('SELECT * FROM clinical_entries WHERE id=? AND hospital_id=? AND author_id=?',(d.get('id'),hid,u['id'])).fetchone()
  if not entry:h.send(404,{'error':'Own clinical entry not found'});return True
  if entry['status']=='signed':raise ValueError('Signed entry is immutable; add a linked correction')
  action=d.get('action')
  if action=='sign':
   if set(d)!={'id','action','version','confirm'} or d['confirm'] is not True:raise ValueError('Explicit signing confirmation required')
   cur=c.execute("UPDATE clinical_entries SET status='signed',signed_at=?,version=version+1 WHERE id=? AND version=?",(datetime.now(timezone.utc).isoformat(),entry['id'],d.get('version')))
  elif action=='edit':
   if set(d)-{'id','action','version','fields','care_at'}:raise ValueError('Unknown draft field')
   fields=d.get('fields');care=stamp(d.get('care_at',entry['care_at']))
   if datetime.fromisoformat(care)>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('Care time cannot be in the future')
   if not isinstance(fields,dict) or set(fields)-set(TEMPLATES[entry['entry_type']]) or not any(isinstance(v,str) and v.strip() for v in fields.values()) or any(not isinstance(v,str) or len(v)>10000 for v in fields.values()):raise ValueError('Valid observed template content required')
   cur=c.execute('UPDATE clinical_entries SET fields=?,care_at=?,version=version+1 WHERE id=? AND version=?',(json.dumps(fields),care,entry['id'],d.get('version')))
  else:raise ValueError('Edit or sign the draft')
  if not cur.rowcount:h.send(409,{'error':'Entry changed; refresh and retry'});return True
  h.audit(c,u,'chart-'+action,'clinical-entry',entry['id']);h.send(200,{'ok':True});return True
 if path=='/api/duty-shifts':
  if method=='POST':
   if not admin:h.send(403,{'error':'Hospital administrator assigns shifts'});return True
   if set(d)-{'staff_id','department','shift_name','starts_at','ends_at','responsibility','on_call','supervisor_id','covering_id'}:raise ValueError('Unknown roster field')
   who=staff(c,d.get('staff_id'),hid);start=stamp(d.get('starts_at'));end=stamp(d.get('ends_at'))
   if end<=start or datetime.fromisoformat(end)-datetime.fromisoformat(start)>timedelta(hours=24):raise ValueError('Shift must last at most 24 hours and end after its start')
   if not available(c,who['id'],hid,start,end):raise ValueError('Staff member has an overlapping duty or approved leave')
   if not d.get('department') or not d.get('shift_name'):raise ValueError('Department and shift name required')
   for key in ('supervisor_id','covering_id'):
    if d.get(key):staff(c,d[key],hid)
   oncall=d.get('on_call','none')
   if oncall not in ('none','primary','backup'):raise ValueError('Valid on-call coverage required')
   cur=c.execute('INSERT INTO duty_shifts(hospital_id,staff_id,department,shift_name,starts_at,ends_at,responsibility,on_call,supervisor_id,covering_id) VALUES(?,?,?,?,?,?,?,?,?,?)',(hid,who['id'],d['department'],d['shift_name'],start,end,d.get('responsibility',''),oncall,d.get('supervisor_id'),d.get('covering_id')))
   h.audit(c,u,'shift-create','duty-shift',cur.lastrowid);h.send(200,{'id':cur.lastrowid});return True
  shift=c.execute('SELECT * FROM duty_shifts WHERE id=? AND hospital_id=?',(d.get('id'),hid)).fetchone()
  if not shift or (not admin and shift['staff_id']!=u['id']):h.send(404,{'error':'Shift not found'});return True
  if d.get('version')!=shift['version']:h.send(409,{'error':'Shift changed; refresh and retry'});return True
  action=d.get('action');now=datetime.now(timezone.utc).isoformat()
  if action in ('clock-in','clock-out'):
   if shift['staff_id']!=u['id']:raise ValueError('Staff must record their own attendance')
   if action=='clock-in':
    if shift['attendance']!='scheduled' or datetime.fromisoformat(shift['starts_at'])-timedelta(minutes=30)>datetime.now(timezone.utc) or shift['ends_at']<now:raise ValueError('Clock in only for a current scheduled shift')
    c.execute("UPDATE duty_shifts SET attendance='checked-in',clocked_in_at=?,version=version+1 WHERE id=?",(now,shift['id']))
   else:
    if shift['attendance']!='checked-in':raise ValueError('Clock in before clocking out')
    c.execute("UPDATE duty_shifts SET attendance='checked-out',clocked_out_at=?,version=version+1 WHERE id=?",(now,shift['id']))
  elif action=='absence':
   if shift['attendance']!='scheduled':raise ValueError('Only a scheduled shift can be reported absent')
   c.execute("UPDATE duty_shifts SET attendance='absent',version=version+1 WHERE id=?",(shift['id'],))
  elif action=='replace':
   if not admin:h.send(403,{'error':'Administrator approves replacements'});return True
   replacement=staff(c,d.get('replacement_id'),hid);old=staff(c,shift['staff_id'],hid)
   if replacement['id']==old['id'] or replacement['role']!=old['role'] or not available(c,replacement['id'],hid,shift['starts_at'],shift['ends_at']):raise ValueError('Choose an available replacement with the same clinical role')
   if shift['attendance'] not in ('scheduled','absent'):raise ValueError('Only scheduled or absent duties may be reassigned')
   c.execute("UPDATE duty_shifts SET replacement_for_id=staff_id,staff_id=?,attendance='scheduled',version=version+1 WHERE id=?",(replacement['id'],shift['id']))
  elif action=='handover':
   entry=c.execute("SELECT * FROM clinical_entries WHERE id=? AND hospital_id=? AND author_id=? AND status='signed' AND entry_type IN ('nursing_handover','clinical_handover')",(d.get('entry_id'),hid,u['id'])).fetchone()
   if not entry or not c.execute('SELECT 1 FROM shift_patients WHERE shift_id=? AND patient_id=? AND hospital_id=?',(shift['id'],entry['patient_id'],hid)).fetchone():raise ValueError('Signed handover for an assigned patient required')
   # Each patient needs a signed handover by this staff member within this shift's care window.
   missing=c.execute("SELECT 1 FROM shift_patients sp WHERE sp.shift_id=? AND NOT EXISTS(SELECT 1 FROM clinical_entries e WHERE e.patient_id=sp.patient_id AND e.hospital_id=? AND e.author_id=? AND e.status='signed' AND e.entry_type IN ('nursing_handover','clinical_handover') AND e.care_at>=? AND e.care_at<=?)",(shift['id'],hid,shift['staff_id'],shift['starts_at'],shift['ends_at'])).fetchone()
   if missing:raise ValueError('Complete a signed handover for every assigned patient')
   c.execute("UPDATE duty_shifts SET handover='completed',handover_entry_id=?,version=version+1 WHERE id=?",(entry['id'],shift['id']))
  else:raise ValueError('Valid roster action required')
  h.audit(c,u,'shift-'+action,'duty-shift',shift['id']);h.send(200,{'ok':True});return True
 if path=='/api/shift-patients':
  if not admin:h.send(403,{'error':'Hospital administrator assigns patients'});return True
  shift=c.execute('SELECT * FROM duty_shifts WHERE id=? AND hospital_id=?',(d.get('shift_id'),hid)).fetchone()
  if not shift or shift['handover']=='completed':raise ValueError('Local shift with pending handover required')
  pid=d.get('patient_id')
  if not c.execute('SELECT 1 FROM patients WHERE id=? AND hospital_id=?',(pid,hid)).fetchone():raise ValueError('Local patient required')
  if d.get('action','assign')=='unassign':c.execute('DELETE FROM shift_patients WHERE shift_id=? AND patient_id=?',(shift['id'],pid))
  elif d.get('action','assign')=='assign':c.execute('INSERT OR IGNORE INTO shift_patients VALUES(?,?,?)',(shift['id'],pid,hid))
  else:raise ValueError('Assign or unassign a patient')
  h.audit(c,u,'shift-patient-'+d.get('action','assign'),'duty-shift',shift['id']);h.send(200,{'ok':True});return True
 if path=='/api/staff-leave':
  if method=='POST':
   start=stamp(d.get('starts_at'));end=stamp(d.get('ends_at'))
   if end<=start or not isinstance(d.get('reason'),str) or not 3<=len(d['reason'])<=1000:raise ValueError('Valid leave interval and reason required')
   staff(c,u['id'],hid)
   cur=c.execute('INSERT INTO staff_leave(hospital_id,staff_id,starts_at,ends_at,reason) VALUES(?,?,?,?,?)',(hid,u['id'],start,end,d['reason']))
   h.audit(c,u,'leave-request','staff-leave',cur.lastrowid);h.send(200,{'id':cur.lastrowid});return True
  if not admin:h.send(403,{'error':'Administrator reviews leave'});return True
  leave=c.execute("SELECT * FROM staff_leave WHERE id=? AND hospital_id=? AND status='pending'",(d.get('id'),hid)).fetchone()
  if not leave:h.send(409,{'error':'Pending leave not found'});return True
  state=d.get('status')
  if state not in ('approved','rejected'):raise ValueError('Approve or reject leave')
  if state=='approved' and not available(c,leave['staff_id'],hid,leave['starts_at'],leave['ends_at']):raise ValueError('Arrange duty coverage before approving overlapping leave')
  c.execute('UPDATE staff_leave SET status=?,reviewed_by=? WHERE id=?',(state,u['id'],leave['id']))
  h.audit(c,u,'leave-'+state,'staff-leave',leave['id']);h.send(200,{'ok':True});return True
 if path=='/api/shift-swaps':
  if method=='POST':
   first=c.execute('SELECT * FROM duty_shifts WHERE id=? AND hospital_id=? AND staff_id=?',(d.get('shift_id'),hid,u['id'])).fetchone()
   second=c.execute('SELECT * FROM duty_shifts WHERE id=? AND hospital_id=?',(d.get('target_shift_id'),hid)).fetchone()
   if not first or not second or first['staff_id']==second['staff_id'] or first['attendance']!='scheduled' or second['attendance']!='scheduled':raise ValueError('Two scheduled shifts belonging to different local staff required')
   if staff(c,first['staff_id'],hid)['role']!=staff(c,second['staff_id'],hid)['role']:raise ValueError('Swap requires matching clinical roles')
   cur=c.execute('INSERT INTO shift_swaps(hospital_id,shift_id,target_shift_id,requester_id,target_id,shift_version,target_version) VALUES(?,?,?,?,?,?,?)',(hid,first['id'],second['id'],u['id'],second['staff_id'],first['version'],second['version']))
   h.audit(c,u,'swap-request','shift-swap',cur.lastrowid);h.send(200,{'id':cur.lastrowid});return True
  swap=c.execute('SELECT * FROM shift_swaps WHERE id=? AND hospital_id=?',(d.get('id'),hid)).fetchone()
  if not swap:h.send(404,{'error':'Swap not found'});return True
  action=d.get('action')
  if action=='accept':
   if swap['target_id']!=u['id'] or swap['status']!='requested':raise ValueError('Only the requested colleague may accept a pending swap')
   c.execute("UPDATE shift_swaps SET status='accepted' WHERE id=?",(swap['id'],))
  elif action=='reject':
   if not admin and u['id'] not in (swap['requester_id'],swap['target_id']):raise ValueError('Swap participant or administrator required')
   if swap['status'] not in ('requested','accepted'):raise ValueError('Swap is already closed')
   c.execute("UPDATE shift_swaps SET status='rejected',reviewed_by=? WHERE id=?",(u['id'],swap['id']))
  elif action=='approve':
   if not admin or swap['status']!='accepted':raise ValueError('Administrator approval requires colleague acceptance')
   first=c.execute('SELECT * FROM duty_shifts WHERE id=?',(swap['shift_id'],)).fetchone();second=c.execute('SELECT * FROM duty_shifts WHERE id=?',(swap['target_shift_id'],)).fetchone()
   if staff(c,first['staff_id'],hid)['role']!=staff(c,second['staff_id'],hid)['role']:raise ValueError('Active staff with matching roles required')
   if first['version']!=swap['shift_version'] or second['version']!=swap['target_version'] or first['staff_id']!=swap['requester_id'] or second['staff_id']!=swap['target_id']:raise ValueError('Shifts changed; request a new swap')
   if not available(c,second['staff_id'],hid,first['starts_at'],first['ends_at'],(first['id'],second['id'])) or not available(c,first['staff_id'],hid,second['starts_at'],second['ends_at'],(first['id'],second['id'])):raise ValueError('Swap conflicts with another shift or approved leave')
   c.execute('UPDATE duty_shifts SET staff_id=?,version=version+1 WHERE id=?',(second['staff_id'],first['id']));c.execute('UPDATE duty_shifts SET staff_id=?,version=version+1 WHERE id=?',(first['staff_id'],second['id']))
   c.execute("UPDATE shift_swaps SET status='approved',reviewed_by=? WHERE id=?",(u['id'],swap['id']))
  else:raise ValueError('Valid swap action required')
  h.audit(c,u,'swap-'+action,'shift-swap',swap['id']);h.send(200,{'ok':True});return True
 h.send(405,{'error':'Unsupported ward action'});return True
