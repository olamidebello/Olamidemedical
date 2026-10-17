"""Tenant-scoped practice, knowledge, staffing and insurance workflows."""
from datetime import date,datetime
from urllib.parse import urlparse

MODULES={
 'charities':['name','registration_number','contact_email','phone','description','status'],
 'sponsorships':['patient_id','charity_id','invoice_id','amount_cents','reference','status'],
 'coupons':['code','description','discount_type','discount_value','minimum_cents','maximum_discount_cents','usage_limit','expires','status'],
 'coupon_redemptions':['patient_id','coupon_id','invoice_id','reference','discount_cents','original_amount_cents'],
 'alerts':['title','message','severity','audience','assigned_user_id','due_at','response','status'],
 'professionals':['user_id','name','profession','specialty','license_number','license_jurisdiction','license_expiry','credential_status','consultation_fee_cents','currency','phone','email','bio','status'],
 'availability':['professional_id','starts_at','ends_at','mode','status'],
 'knowledge_articles':['title','category','content','source_url','reviewed_by','status'],
 'staff_requests':['title','question','urgency','assigned_user_id','response','status'],
 'payers':['name','payer_code','phone','contact_email','status'],
 'policies':['patient_id','payer_id','member_id','group_number','coverage_start','coverage_end','verification_reference','status'],
 'authorizations':['patient_id','policy_id','procedure_code','authorized_units','used_units','expires','reference','status'],
 'claims':['patient_id','policy_id','invoice_id','authorization_id','diagnosis_codes','procedure_codes','amount_cents','payer_reference','submitted_at','status'],
 'remittances':['patient_id','claim_id','amount_cents','adjustment_cents','reference','reason','posted_at'],
}
STATES={
 'charities':['active','inactive'],'sponsorships':['requested','approved','paid','rejected'],'coupons':['active','inactive'],'alerts':['open','acknowledged','resolved'],
 'professionals':['active','inactive','suspended'], 'availability':['available','booked','unavailable'],
 'knowledge_articles':['draft','published','archived'],'staff_requests':['open','claimed','resolved'],
 'payers':['active','inactive'],'policies':['unverified','verified','expired','cancelled'],
 'authorizations':['requested','approved','denied','expired'], 'claims':['draft','submitted','pending','approved','denied','paid','void']
}
LINKS={'charity_id':'charities','coupon_id':'coupons','payer_id':'payers','policy_id':'policies','authorization_id':'authorizations','claim_id':'claims','professional_id':'professionals','user_id':'users','assigned_user_id':'users'}
BILLING={'charities','sponsorships','coupons','coupon_redemptions','payers','policies','authorizations','claims','remittances'}
CARE={'alerts','professionals','availability','knowledge_articles','staff_requests'}
NUMERIC={'discount_value','minimum_cents','maximum_discount_cents','usage_limit','discount_cents','original_amount_cents','consultation_fee_cents','authorized_units','used_units','adjustment_cents'}


def validate(c,u,table,d,merged,old):
    if table not in MODULES:return
    if table in ('professionals','availability','payers') and u['role']!='admin':raise ValueError('Hospital administrator required to change this registry')
    if table=='knowledge_articles':
        if u['role'] not in ('admin','clinician'):raise ValueError('Hospital administrator or clinician required to author knowledge articles')
        if not merged.get('title') or not merged.get('content'):raise ValueError('Article title and content required')
        if merged.get('source_url') and (urlparse(merged['source_url']).scheme!='https' or not urlparse(merged['source_url']).netloc):raise ValueError('Use an HTTPS source reference')
        if merged.get('status')=='published' and not merged.get('reviewed_by'):raise ValueError('Published article requires a recorded reviewer')
    if table=='staff_requests':
        if not merged.get('title') or not merged.get('question'):raise ValueError('Request title and question required')
        if merged.get('urgency','routine') not in ('routine','urgent'):raise ValueError('Routine or urgent priority required')
        if merged.get('assigned_user_id'):
            role=c.execute('SELECT role,active FROM users WHERE id=? AND hospital_id=?',(merged['assigned_user_id'],u['hospital_id'])).fetchone()
            if not role or not role['active'] or role['role'] not in ('admin','clinician','nurse'):raise ValueError('Assign an active local care-team member')
        if merged.get('status')=='resolved' and not merged.get('response'):raise ValueError('Record a response before resolving')
    if table=='professionals':
        if not merged.get('name') or merged.get('profession') not in ('doctor','nurse'):raise ValueError('Professional name and doctor/nurse profession required')
        if merged.get('credential_status','unverified') not in ('unverified','reviewed','expired','suspended'):raise ValueError('Valid credential review status required')
        if merged.get('credential_status')=='reviewed' and not all(merged.get(k) for k in ('license_number','license_jurisdiction','license_expiry')):raise ValueError('License number, jurisdiction and expiry required for reviewed credentials')
        if merged.get('license_expiry'):date.fromisoformat(merged['license_expiry'])
        if merged.get('user_id'):
            user=c.execute('SELECT * FROM users WHERE id=? AND hospital_id=?',(merged['user_id'],u['hospital_id'])).fetchone()
            required='clinician' if merged['profession']=='doctor' else 'nurse'
            if not user or not user['active'] or user['role']!=required:raise ValueError('Link an active local account with the matching clinician/nurse role')
            if c.execute('SELECT 1 FROM professionals WHERE user_id=? AND id!=?',(merged['user_id'],old['id'] if old else 0)).fetchone():raise ValueError('This user already has a professional profile')
        if merged.get('currency') and (len(merged['currency'])!=3 or not merged['currency'].isalpha()):raise ValueError('Three-letter currency code required')
    if table=='availability':
        if not merged.get('professional_id') or merged.get('mode') not in ('in-person','video','audio'):raise ValueError('Professional and supported consultation mode required')
        start=datetime.fromisoformat(merged.get('starts_at',''));end=datetime.fromisoformat(merged.get('ends_at',''))
        if start.tzinfo is None or end.tzinfo is None or end<=start:raise ValueError('Availability requires timezone-aware start/end times in order')
        if merged.get('status','available')!='unavailable' and c.execute("SELECT 1 FROM availability WHERE hospital_id=? AND professional_id=? AND status!='unavailable' AND id!=? AND julianday(starts_at)<julianday(?) AND julianday(ends_at)>julianday(?)",(u['hospital_id'],merged['professional_id'],old['id'] if old else 0,merged['ends_at'],merged['starts_at'])).fetchone():raise ValueError('Availability overlaps an existing slot')
    for key in NUMERIC:
        if key in d:
            if isinstance(d[key],bool) or str(d[key])!=str(int(d[key])) or int(d[key])<0:raise ValueError(key+' must be a nonnegative integer')
            d[key]=int(d[key])
    if table=='payers' and not all(merged.get(k) for k in ('name','payer_code')):raise ValueError('Payer name and identifier required')
    if table=='policies':
        if not all(merged.get(k) for k in ('payer_id','member_id','coverage_start','coverage_end')):raise ValueError('Payer, member ID and coverage dates required')
        start=date.fromisoformat(merged['coverage_start']);end=date.fromisoformat(merged['coverage_end'])
        if end<start:raise ValueError('Coverage end must follow coverage start')
        if merged.get('status')=='verified' and not merged.get('verification_reference'):raise ValueError('Record the manual eligibility verification reference')
    for key in ('policy_id','claim_id','authorization_id','invoice_id'):
        if merged.get(key):
            target=LINKS.get(key,'invoices')
            linked=c.execute(f'SELECT * FROM {target} WHERE id=? AND hospital_id=?',(merged[key],u['hospital_id'])).fetchone()
            if not linked or linked['patient_id']!=merged.get('patient_id'):raise ValueError('Insurance links must belong to the same local patient')
    if table=='authorizations':
        if not merged.get('policy_id') or not merged.get('procedure_code'):raise ValueError('Policy and procedure required')
        if int(merged.get('used_units') or 0)>int(merged.get('authorized_units') or 0):raise ValueError('Used units exceed authorized units')
        if merged.get('expires'):date.fromisoformat(merged['expires'])
        if merged.get('status')=='approved' and not merged.get('reference'):raise ValueError('Approved authorization requires a payer reference')
    if table=='claims':
        if not all(merged.get(k) for k in ('policy_id','invoice_id','procedure_codes','amount_cents')):raise ValueError('Policy, invoice, procedure and positive amount required')
        invoice=c.execute('SELECT amount_cents FROM invoices WHERE id=? AND hospital_id=?',(merged['invoice_id'],u['hospital_id'])).fetchone()
        if int(merged['amount_cents'])>int(invoice['amount_cents']):raise ValueError('Claim exceeds its invoice amount')
        if merged.get('status') not in (None,'draft','void') and not merged.get('payer_reference'):raise ValueError('Record the external payer submission/reference before advancing claim status')
        if merged.get('status')=='paid':raise ValueError('Paid claim status is calculated from remittances')
        if old and c.execute('SELECT 1 FROM remittances WHERE claim_id=?',(old['id'],)).fetchone():raise ValueError('Claims with posted remittances are immutable')
    if table=='alerts':
        if not merged.get('title') or not merged.get('message'):raise ValueError('Alert title and message required')
        if merged.get('severity') not in ('info','warning','urgent'):raise ValueError('Valid alert severity required')
        if merged.get('audience') not in ('admin','clinician','nurse','billing','clinical','staff'):raise ValueError('Choose a staff audience')
        if merged.get('status')=='resolved' and not merged.get('response'):raise ValueError('Record a resolution response')
    if table=='charities' and not all(merged.get(k) for k in ('name','registration_number')):raise ValueError('Charity name and registration identifier required')
    if table=='sponsorships':
        if not all(merged.get(k) for k in ('charity_id','invoice_id','amount_cents','reference')):raise ValueError('Charity, invoice, positive amount and reference required')
        charity=c.execute('SELECT status FROM charities WHERE id=? AND hospital_id=?',(merged['charity_id'],u['hospital_id'])).fetchone()
        if not charity or charity['status']!='active':raise ValueError('Active local charity required')
    if table=='coupons':
        if not merged.get('code') or merged.get('discount_type') not in ('percent','fixed'):raise ValueError('Coupon code and percent/fixed discount type required')
        value=int(merged.get('discount_value') or 0)
        if value<=0 or (merged['discount_type']=='percent' and value>100):raise ValueError('Positive discount required; percentages cannot exceed 100')
        if not merged.get('expires'):raise ValueError('Coupon expiry date required')
        date.fromisoformat(merged['expires'])
        if int(merged.get('usage_limit') or 0)<=0:raise ValueError('Positive usage limit required')
        if c.execute('SELECT 1 FROM coupons WHERE hospital_id=? AND code=? AND id!=?',(u['hospital_id'],merged['code'],old['id'] if old else 0)).fetchone():raise ValueError('Coupon code already exists')
    if table=='coupon_redemptions':
        if old:raise ValueError('Coupon redemptions are immutable')
        if not merged.get('coupon_id') or not merged.get('invoice_id') or not merged.get('reference'):raise ValueError('Coupon, invoice and reference required')
        coupon=c.execute('SELECT * FROM coupons WHERE id=? AND hospital_id=?',(merged['coupon_id'],u['hospital_id'])).fetchone()
        invoice=c.execute('SELECT * FROM invoices WHERE id=? AND hospital_id=?',(merged['invoice_id'],u['hospital_id'])).fetchone()
        if not coupon or coupon['status']!='active' or coupon['expires']<date.today().isoformat():raise ValueError('Active unexpired coupon required')
        if c.execute("SELECT 1 FROM claims WHERE invoice_id=? AND status!='void'",(merged['invoice_id'],)).fetchone():raise ValueError('Resolve or void existing claims before applying an invoice coupon')
        if not invoice or invoice['status']!='open' or c.execute('SELECT 1 FROM payments WHERE invoice_id=?',(invoice['id'],)).fetchone():raise ValueError('Only open invoices without posted payments can receive a coupon')
        if c.execute('SELECT 1 FROM coupon_redemptions WHERE invoice_id=? OR (hospital_id=? AND reference=?)',(invoice['id'],u['hospital_id'],merged['reference'])).fetchone():raise ValueError('An invoice can redeem one coupon; redemption reference must be unique')
        used=c.execute('SELECT COUNT(*) FROM coupon_redemptions WHERE coupon_id=?',(coupon['id'],)).fetchone()[0]
        if used>=int(coupon['usage_limit']):raise ValueError('Coupon usage limit reached')
        amount=int(invoice['amount_cents'])
        if amount<int(coupon['minimum_cents'] or 0):raise ValueError('Invoice does not meet coupon minimum')
        discount=amount*int(coupon['discount_value'])//100 if coupon['discount_type']=='percent' else int(coupon['discount_value'])
        cap=int(coupon['maximum_discount_cents'] or amount);discount=min(discount,cap,amount)
        if discount<=0:raise ValueError('Coupon produces no applicable discount')
        d['discount_cents']=discount;d['original_amount_cents']=amount
    if table=='remittances':
        if old:raise ValueError('Posted remittances are immutable; record a separate correction workflow')
        if not merged.get('claim_id') or not merged.get('reference'):raise ValueError('Claim and unique remittance reference required')
        claim=c.execute('SELECT * FROM claims WHERE id=? AND hospital_id=?',(merged['claim_id'],u['hospital_id'])).fetchone()
        if claim['status'] in ('draft','void','denied'):raise ValueError('An active submitted claim is required')
        if c.execute('SELECT 1 FROM remittances WHERE hospital_id=? AND reference=?',(u['hospital_id'],merged['reference'])).fetchone():raise ValueError('Duplicate remittance reference')
        total=int(merged.get('amount_cents') or 0)+int(merged.get('adjustment_cents') or 0)
        paid=c.execute('SELECT COALESCE(SUM(amount_cents+COALESCE(adjustment_cents,0)),0) FROM remittances WHERE claim_id=?',(claim['id'],)).fetchone()[0]
        if total<=0 or total+paid>int(claim['amount_cents']):raise ValueError('Remittance must be positive and within the unsettled claim balance')


def after_write(c,u,table,row):
    if table=='coupon_redemptions':
        c.execute("UPDATE invoices SET amount_cents=amount_cents-?,status=CASE WHEN amount_cents=? THEN 'paid' ELSE status END,version=version+1 WHERE id=? AND hospital_id=?",(row['discount_cents'],row['discount_cents'],row['invoice_id'],u['hospital_id']))
    if table=='remittances':
        total=c.execute('SELECT SUM(amount_cents+COALESCE(adjustment_cents,0)) FROM remittances WHERE claim_id=?',(row['claim_id'],)).fetchone()[0]
        c.execute("UPDATE claims SET status=CASE WHEN amount_cents=? THEN 'paid' ELSE 'pending' END,version=version+1 WHERE id=? AND hospital_id=?",(total,row['claim_id'],u['hospital_id']))
