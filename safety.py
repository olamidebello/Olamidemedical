"""Source-linked closed-loop care tracking and an operational safety overview."""
from datetime import datetime,timezone

MODULES={
 'critical_results':['patient_id','result_id','assigned_user_id','severity','due_at','acknowledgment','acknowledged_by','acknowledged_at','resolution','status'],
 'referral_followups':['patient_id','referral_id','assigned_user_id','destination','due_at','acceptance_reference','outcome','status'],
 'medication_reviews':['patient_id','encounter_id','source','medication_list','discrepancies','resolution','reviewed_by','reviewed_at','status'],
 'transition_tasks':['patient_id','encounter_id','assigned_user_id','task','due_at','contact_attempts','outcome','status'],
 'safety_events':['patient_id','event_type','description','severity','immediate_action','assigned_user_id','closure_summary','status']
}
STATES={'critical_results':['open','acknowledged','resolved'],'referral_followups':['requested','accepted','completed','cancelled'],
        'medication_reviews':['draft','reviewed'],'transition_tasks':['open','in-progress','completed','cancelled'],
        'safety_events':['reported','investigating','closed']}
LINKS={'result_id':'results','referral_id':'referrals'}


def validate(c,u,table,d,merged,old):
 if table not in MODULES:return
 if u['role'] not in ('admin','clinician','nurse','pharmacist'):raise ValueError('Care-team access required')
 for link,target in LINKS.items():
  if merged.get(link):
   record=c.execute(f'SELECT * FROM {target} WHERE id=? AND hospital_id=?',(merged[link],u['hospital_id'])).fetchone()
   if not record or record['patient_id']!=merged.get('patient_id'):raise ValueError('Source must belong to this local patient')
 if merged.get('assigned_user_id'):
  owner=c.execute("SELECT * FROM users WHERE id=? AND hospital_id=? AND active=1 AND role IN ('admin','clinician','nurse','pharmacist')",(merged['assigned_user_id'],u['hospital_id'])).fetchone()
  if not owner:raise ValueError('Assign an active local care-team owner')
 if merged.get('due_at'):
  stamp=datetime.fromisoformat(merged['due_at'].replace('Z','+00:00'))
  if stamp.tzinfo is None:raise ValueError('Follow-up deadline must include a timezone')
 if table=='critical_results':
  if not all(merged.get(k) for k in ('result_id','assigned_user_id','severity','due_at')):raise ValueError('Final result, responsible owner, severity and deadline required')
  source=c.execute('SELECT status FROM results WHERE id=? AND hospital_id=?',(merged['result_id'],u['hospital_id'])).fetchone()
  if source['status']!='final':raise ValueError('Only finalized source results can be escalated')
  if merged['severity'] not in ('warning','urgent'):raise ValueError('Warning or urgent severity required')
  if not old and merged.get('status')!='open':raise ValueError('Create a new critical-result task as open')
  if old:
   if old['status']=='resolved':raise ValueError('Resolved communication is immutable; create a new follow-up')
   new=merged.get('status')
   allowed={'open':{'open','acknowledged'},'acknowledged':{'acknowledged','resolved'}}
   if new not in allowed[old['status']]:raise ValueError('Acknowledge the result before resolving')
   if new!=old['status'] and u['role']!='admin' and old['assigned_user_id']!=u['id']:raise ValueError('Responsible owner or hospital administrator must acknowledge/resolve')
  if any(k in d for k in ('acknowledged_by','acknowledged_at')):raise ValueError('Acknowledgment identity/time are server-generated')
  if merged.get('status')=='acknowledged' and (not old or old['status']=='open'):
   if not merged.get('acknowledgment'):raise ValueError('Record the acknowledgment/read-back')
   d['acknowledged_by']=u['username'];d['acknowledged_at']=datetime.now(timezone.utc).isoformat()
  if merged.get('status')=='resolved' and not merged.get('resolution'):raise ValueError('Record the follow-up action before closure')
 if table=='referral_followups':
  if not all(merged.get(k) for k in ('referral_id','assigned_user_id','destination','due_at')):raise ValueError('Referral, owner, destination and follow-up deadline required')
  if old and old['status'] in ('completed','cancelled'):raise ValueError('Closed referral follow-up is immutable')
  if merged.get('status') in ('accepted','completed') and not merged.get('acceptance_reference'):raise ValueError('Record receiving-provider acceptance')
  if merged.get('status')=='completed' and not merged.get('outcome'):raise ValueError('Record the received consultation/outcome before closing the loop')
 if table=='medication_reviews':
  if not all(merged.get(k) for k in ('source','medication_list')):raise ValueError('Medication information source and reviewed list required')
  if old and old['status']=='reviewed':raise ValueError('Completed medication review is immutable; create a new review')
  if any(k in d for k in ('reviewed_by','reviewed_at')):raise ValueError('Review identity/time are server-generated')
  if merged.get('status')=='reviewed':
   if not merged.get('resolution'):raise ValueError('Document reconciliation findings/resolution')
   d['reviewed_by']=u['username'];d['reviewed_at']=datetime.now(timezone.utc).isoformat()
 if table=='transition_tasks':
  if not all(merged.get(k) for k in ('assigned_user_id','task','due_at')):raise ValueError('Task, owner and deadline required')
  if old and old['status'] in ('completed','cancelled'):raise ValueError('Closed transition task is immutable')
  if merged.get('status')=='completed' and not merged.get('outcome'):raise ValueError('Record the completed follow-up outcome')
 if table=='safety_events':
  if not all(merged.get(k) for k in ('event_type','description','severity','immediate_action')):raise ValueError('Event type, description, severity and immediate response required')
  if old and old['status']=='closed':raise ValueError('Closed event is immutable; create a linked narrative in a new report')
  if merged.get('status')=='closed' and (u['role']!='admin' or not merged.get('closure_summary')):raise ValueError('Hospital administrator records closure summary')


def handle(h,c,u,path,method):
 if path!='/api/safety-overview':return False
 if method!='GET' or u['role'] not in ('admin','clinician','nurse','pharmacist'):h.send(403,{'error':'Local care-team access required'});return True
 hid=u['hospital_id'];counts={}
 for name,condition in [
  ('critical_results',"status!='resolved'"),('referral_followups',"status NOT IN ('completed','cancelled')"),
  ('medication_reviews',"status='draft'"),('transition_tasks',"status NOT IN ('completed','cancelled')"),
  ('safety_events',"status!='closed'"),('device_readings',"status='pending'"),
  ('staff_requests',"status!='resolved' AND urgency='urgent'")
 ]:counts[name]=c.execute(f'SELECT COUNT(*) FROM {name} WHERE hospital_id=? AND '+condition,(hid,)).fetchone()[0]
 duplicates=[dict(r) for r in c.execute('''SELECT lower(trim(name)) AS normalized_name,dob,COUNT(*) AS records
     FROM patients WHERE hospital_id=? GROUP BY lower(trim(name)),dob HAVING COUNT(*)>1 LIMIT 100''',(hid,))]
 h.audit(c,u,'read','safety-overview')
 h.send(200,{'pending':counts,'identity_review_candidates':duplicates,'notice':'Operational review queues, not automated diagnoses, a clinical risk score or an emergency alarm. Identity candidates are not automatically merged.'});return True
