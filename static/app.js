let me, module, records=[], selected;
const $=id=>document.getElementById(id);
const labels={patients:'Patient registration',appointments:'Scheduling',encounters:'Encounters & admissions',notes:'Clinical notes',allergies:'Allergies',medications:'Medications',vitals:'Vitals & observations',orders:'Clinical orders',results:'Diagnostic results',care_plans:'Care plans',referrals:'Referrals & authorizations',beds:'Beds & capacity',inventory:'Pharmacy inventory',prescriptions:'Prescriptions',administrations:'Medication administration',invoices:'Billing & charges',payments:'Payment ledger',messages:'In Basket & messages',workqueues:'Workqueues',specialty_cases:'Specialty procedures',outreach:'Population health',documents:'Documents & consent',immunizations:'Immunizations',history:'Patient history',care_team:'Care team',registrations:'Registrations & onboarding',professionals:'Provider registration & management',knowledge:'Knowledge & staff aid',telemedicine:'Telemedicine',devices:'Medical devices',mobility:'Patient mobility',audit:'Audit trail',hospitals:'Hospital administration','hospital-users':'Staff & access','tenant-audit':'Administration audit'};
Object.assign(labels,{safety:'Safety Command Center',critical_results:'Critical result acknowledgment',referral_followups:'Referral follow-up',medication_reviews:'Medication reconciliation',transition_tasks:'Care transition tasks',safety_events:'Safety event reports',nursing:'Nursing Station',doctor:'Doctor Workspace',rosters:'Staff Scheduling',attendance:'Attendance & Leave',coverage:'Coverage & Supervisor',availability:'Practitioner availability',knowledge_articles:'Knowledge articles',staff_requests:'Staff aid requests',payers:'Insurance payers',policies:'Patient coverage',authorizations:'Prior authorizations',claims:'Insurance claims',remittances:'Remittances',charities:'Charity organizations',sponsorships:'Patient sponsorships',coupons:'Coupon controls',coupon_redemptions:'Coupon redemptions',alerts:'Alerts & escalation',ai:'AI knowledge assistance'});
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
async function api(path,method='GET',data){const r=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-Requested-With':'OlamideMedical'},body:data?JSON.stringify(data):undefined});const d=await r.json();if(!r.ok){if(r.status===401){$('app').hidden=true;$('login').hidden=false}throw Error(d.error)}return d}
$('loginform').onsubmit=async e=>{e.preventDefault();try{await api('login','POST',Object.fromEntries(new FormData(e.target)));await start()}catch(e){$('loginerror').textContent=e.message}};
async function start(){try{me=await api('me');$('login').hidden=true;$('app').hidden=false;$('identity').textContent=me.username+' · '+me.role+' · '+(me.hospital?.name||'Platform administration');let modules=Object.keys(labels).filter(x=>me.modules.includes(x));if(me.role==='patient')modules=Object.keys(labels).filter(x=>['patients','appointments','medications','results','care_plans','invoices','messages','immunizations','documents','care_team'].includes(x));if(me.role==='admin')modules.push('audit','hospital-users','tenant-audit','registrations');if(me.role==='super_admin')modules.push('hospitals','hospital-users','tenant-audit','registrations');if(['admin','clinician','nurse','pharmacist','reception'].includes(me.role))modules.push('mobility');if(['admin','clinician','nurse'].includes(me.role))modules.push('devices','professionals','knowledge','ai','rosters','attendance','coverage','safety');if(['admin','nurse'].includes(me.role))modules.push('nursing');if(['admin','clinician'].includes(me.role))modules.push('doctor');if(['admin','clinician','nurse','reception','patient'].includes(me.role))modules.push('telemedicine');renderNavigation([...new Set(modules)]);overview()}catch(e){$('loginerror').textContent=e.message}}
$('logout').onclick=async()=>{await api('logout','POST',{});location.reload()};
$('navsearch').oninput=e=>{for(const b of $('nav').children)b.hidden=!b.textContent.toLowerCase().includes(e.target.value.toLowerCase())};
async function overview(){
 closeConsultation();if(me.role==='super_admin')return managementView('hospitals');module=null;
 $('title').textContent=me.role==='patient'?'Your care workspace':'Your daily workspace';$('workspace').hidden=true;$('dashboard').hidden=false;
 const root=$('dashboard');root.replaceChildren();const welcome=el('section',undefined,'welcome');welcome.append(el('small',me.hospital?.name||'Olamide Medical'),el('h2',me.role==='nurse'?'Ready for your next patient.':me.role==='clinician'?'Your care team, connected.':'Everything you need, in one place.'),el('p','Choose a workspace below. Your hospital’s records and permissions apply throughout.'));root.append(welcome);
 const visible=[...$('nav').querySelectorAll('[data-module]')].map(b=>b.dataset.module);
 const priorities=['safety','nursing','doctor','rosters','attendance','telemedicine','patients','appointments','knowledge','alerts','registrations','professionals','policies','claims','charities','coupons','mobility','devices'];
 const actions=el('div',undefined,'cards');for(const key of priorities.filter(k=>visible.includes(k)).slice(0,8)){const b=el('button',undefined,'card');b.append(el('strong',labels[key]),el('small','Open workspace →'));b.onclick=()=>open(key);actions.append(b)}root.append(actions);
 const stats=el('div',undefined,'cards');root.append(el('h2','Recent activity'),stats);
 const names=['patients','appointments','encounters','orders','invoices','alerts'].filter(k=>me.modules.includes(k)).slice(0,6);
 await Promise.all(names.map(async name=>{const card=el('button',undefined,'card');card.append(el('span',labels[name]),el('strong','…'),el('small','Recent records · up to 500'));card.onclick=()=>open(name);stats.append(card);try{const rows=await api(name);card.querySelector('strong').textContent=rows.length+(rows.length===500?'+':'')}catch{card.querySelector('strong').textContent='Unavailable'}}));
}

async function open(m){if(m==='safety')return safetyView();if(['nursing','doctor'].includes(m))return chartingView(m);if(['rosters','attendance','coverage'].includes(m))return rosterView(m);if(m==='registrations')return registrationView();if(m==='professionals')return professionalsView();if(m==='knowledge')return knowledgeView();if(m==='telemedicine')return telemedicineView();if(m==='devices')return deviceView();if(m==='mobility')return portabilityView();if(['hospitals','hospital-users'].includes(m))return managementView(m);if(m==='ai')return aiView();return recordView(m)}
async function recordView(m){closeConsultation();module=m;$('title').textContent=labels[m];$('dashboard').hidden=true;$('workspace').hidden=false;$('error').textContent='';$('search').value='';$('new').hidden=['audit','tenant-audit'].includes(m)||(me.role==='patient'&&!me.modules.includes(m));try{records=await api(m);render()}catch(e){$('error').textContent=e.message}}
function render(){const filter=$('search').value.toLowerCase();const rows=records.filter(r=>JSON.stringify(r).toLowerCase().includes(filter));$('table').replaceChildren();if(!rows.length){$('table').append(el('p','No matching records. Add a record to begin.','empty'));return}const table=el('table'),head=el('tr');const keys=Object.keys(rows[0]).filter(k=>!['created_by','updated_at','version'].includes(k));keys.forEach(k=>head.append(el('th',k.replaceAll('_',' '))));head.append(el('th','Actions'));table.append(head);rows.forEach(r=>{const tr=el('tr');keys.forEach(k=>tr.append(el('td',String(r[k]??'—'))));let td=el('td');if(!['audit','tenant-audit'].includes(module)&&!(me.role==='patient'&&!me.modules.includes(module))){let b=el('button','Open / edit');b.onclick=()=>edit(r);td.append(b)}tr.append(td);table.append(tr)});$('table').append(table)}
$('search').oninput=render;$('refresh').onclick=()=>module?open(module):overview();$('new').onclick=()=>edit(null);$('close').onclick=()=>$('editor').close();
async function edit(r){
 selected=r;const targetModule=module;$('editortitle').textContent=(r?'Edit ':'New ')+labels[module];$('fields').replaceChildren();$('formerror').textContent='';$('editor').showModal();$('save').disabled=true;
 const choices={profession:['doctor','nurse','pharmacist','dentist','therapist','allied_health'],credential_status:['unverified','reviewed','expired','suspended'],mode:['in-person','video','audio'],discount_type:['percent','fixed'],severity:['info','warning','urgent'],audience:['admin','clinician','nurse','billing','clinical','staff'],urgency:['routine','urgent']};
 const links={result_id:'results',referral_id:'referrals',patient_id:'patients',encounter_id:'encounters',order_id:'orders',medication_id:'medications',inventory_id:'inventory',invoice_id:'invoices',payer_id:'payers',policy_id:'policies',authorization_id:'authorizations',claim_id:'claims',charity_id:'charities',coupon_id:'coupons',professional_id:'professionals',user_id:'staff-directory',assigned_user_id:'staff-directory'};
 const linked={};
 try{
  await Promise.all([...new Set(me.schema[targetModule].map(k=>links[k]).filter(Boolean))].map(async path=>{try{linked[path]=await api(path)}catch{linked[path]=[]}}));
  if(module!==targetModule)return;
  for(const key of me.schema[module]){
   if(me.role==='patient'&&key==='patient_id')continue;
   const label=el('label',pretty(key));let input;
   if(links[key]){input=el('select');const empty=el('option','Select '+pretty(key.replace(/_id$/,''))+' (optional unless required)');empty.value='';input.append(empty);input.dataset.link=links[key];}
   else if((key==='status'&&me.states[module])||choices[key]){input=el('select');for(const value of choices[key]||me.states[module]){const o=el('option',pretty(value));o.value=value;input.append(o)}}
   else if(['content','findings','description','intervention','address','question','response','bio','message','acknowledgment','resolution','medication_list','discrepancies','outcome','immediate_action','closure_summary'].includes(key))input=el('textarea');
   else{input=el('input');input.type=numericField(key)?'number':['dob','expiry','license_expiry','coverage_start','coverage_end','expires'].includes(key)?'date':key.endsWith('_at')?'datetime-local':'text';if(input.type==='number'){input.min='0';input.step='1'}}
   if(['starts_at','ends_at'].includes(key))input.type='datetime-local';input.name=key;
   if(r&&r[key]!=null&&!links[key])input.value=input.type==='datetime-local'?toLocalDateInput(r[key]):r[key];
   if((['acknowledged_by','acknowledged_at'].includes(key)&&module==='critical_results')||(['reviewed_by','reviewed_at'].includes(key)&&module==='medication_reviews')||(['discount_cents','original_amount_cents'].includes(key)&&module==='coupon_redemptions')){input.readOnly=true;input.placeholder='Calculated by the server'}
   label.append(input);$('fields').append(label);
  }
  const f=$('recordform');
  let initialLinks=true;const updateLinks=()=>{const pid=Number(f.elements.patient_id?.value||r?.patient_id||0);
   for(const key of me.schema[module].filter(k=>links[k])){const input=f.elements[key];if(!input)continue;const current=input.value||(initialLinks?String(r?.[key]||''):'');while(input.options.length>1)input.remove(1);
    const rows=(linked[links[key]]||[]).filter(item=>!pid||key==='patient_id'||item.patient_id===undefined||Number(item.patient_id)===pid);
    for(const item of rows){const o=el('option',recordLabel(item,links[key]));o.value=item.id;input.append(o)}
    if(initialLinks&&current&&!rows.some(item=>String(item.id)===current)){const o=el('option','Existing link #'+current);o.value=current;input.append(o)}input.value=current;
   }
  };updateLinks();initialLinks=false;if(f.elements.patient_id)f.elements.patient_id.onchange=()=>{for(const key of me.schema[module])if(links[key]&&key!=='patient_id'&&f.elements[key])f.elements[key].value='';updateLinks()};
 }catch(e){$('formerror').textContent=e.message}finally{$('save').disabled=false}
}
function recordLabel(row,table){return (row.name||row.title||row.username||row.code||row.description||row.member_id||row.procedure_codes||row.label||pretty(table))+' · '+(row.mrn||row.reference||row.payer_code||'ID '+row.id)+(row.status?' · '+row.status:'')}

$('recordform').onsubmit=async e=>{e.preventDefault();const data={};for(const [k,v] of new FormData(e.target)){if(e.target.elements[k]?.readOnly)continue;if(v!=='')data[k]=numericField(k)?Number(v):v;else if(selected&&k==='patient_id'&&module==='beds')data[k]=null}for(const k of ['starts_at','ends_at','due_at'])if(data[k])data[k]=new Date(data[k]).toISOString();if(selected)data.version=selected.version;$('save').disabled=true;try{await api(module+(selected?'/'+selected.id:''),selected?'PATCH':'POST',data);$('editor').close();await open(module)}catch(e){$('formerror').textContent=e.message}finally{$('save').disabled=false}};
$('export').onclick=()=>{const blob=new Blob([JSON.stringify(records,null,2)],{type:'application/json'});const a=el('a');a.href=URL.createObjectURL(blob);a.download=module+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};start();

// Administrative forms use dedicated APIs; hospital_id is never accepted by clinical editors.
async function managementView(kind){
 closeConsultation();module=kind;$('title').textContent=labels[kind];$('workspace').hidden=true;$('dashboard').hidden=false;$('error').textContent='';
 const root=$('dashboard');root.replaceChildren();
 const message=el('p');message.setAttribute('role','status');root.append(message);
 const run=fn=>async()=>{try{message.textContent='';await fn()}catch(e){message.textContent=e.message}};
 const makeForm=(title,fields,submit)=>{
  const box=el('section',undefined,'admin-panel'),form=el('form');box.append(el('h2',title));
  for(const field of fields){
   const label=el('label',field.label||field.name.replaceAll('_',' '));let input;
   if(field.options){input=el('select');for(const [value,text] of field.options){const option=el('option',text);option.value=value;input.append(option)}}
   else{input=el('input');input.type=field.type||'text'}
   input.name=field.name;input.required=field.required!==false;if(field.value!==undefined)input.value=field.value;
   if(field.type==='password'){input.minLength=12;input.autocomplete='new-password'}
   label.append(input);form.append(label);
  }
  const status=el('p');status.setAttribute('role','status');const save=el('button','Save');form.append(status,save);
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await submit(Object.fromEntries(new FormData(form)));form.reset();await managementView(kind)}catch(e){status.textContent=e.message}finally{save.disabled=false}};
  box.append(form);root.append(box);return box;
 };
 try{
  const platform=me.role==='super_admin';
  const hospitals=platform?await api('hospitals'):[me.hospital];
  if(kind==='hospitals'){
   const stats=el('div',undefined,'cards');
   for(const [label,value] of [['Hospitals',hospitals.length],['Active hospitals',hospitals.filter(h=>h.active).length],['Staff accounts',hospitals.reduce((n,h)=>n+h.users,0)]]){const c=el('div',undefined,'card');c.append(el('span',label),el('strong',String(value)));stats.append(c)}root.append(stats);
   makeForm('Register a hospital',[{name:'name'},{name:'slug',label:'Unique hospital slug (lowercase)'},{name:'organization_type',options:['hospital','private_doctor','private_nurse','clinic'].map(x=>[x,x.replaceAll('_',' ')])},{name:'contact_email',type:'email',required:false}],d=>api('hospitals','POST',d));
  }
  const search=el('input');search.type='search';search.placeholder=kind==='hospitals'?'Search hospitals':'Search staff or roles';search.setAttribute('aria-label',search.placeholder);root.append(search);
  const list=el('div');root.append(list);
  if(kind==='hospitals'){
   const draw=()=>{list.replaceChildren();for(const h of hospitals.filter(h=>(h.name+' '+h.slug).toLowerCase().includes(search.value.toLowerCase()))){
    const card=el('section',undefined,'admin-panel');card.append(el('h2',h.name),el('p',h.slug+' · '+(h.active?'Active':'Suspended')+' · '+h.users+' accounts · '+h.patients+' patients'));
    const toggle=el('button',h.active?'Suspend hospital':'Reactivate hospital');toggle.onclick=run(async()=>{if(h.active&&!confirm('Suspend '+h.name+' and revoke its sessions?'))return;await api('hospitals','PATCH',{id:h.id,version:h.version,active:!h.active});await managementView(kind)});
    const ai=el('button',h.ai_enabled?'Disable AI assistance':'Enable AI assistance');ai.onclick=run(async()=>{await api('hospitals','PATCH',{id:h.id,version:h.version,ai_enabled:!h.ai_enabled});await managementView(kind)});card.append(ai);
    const edit=el('button','Edit hospital');edit.onclick=()=>{makeForm('Edit '+h.name,[{name:'name',value:h.name},{name:'contact_email',type:'email',required:false,value:h.contact_email}],d=>api('hospitals','PATCH',{...d,id:h.id,version:h.version})).scrollIntoView()};card.append(edit,toggle);list.append(card);
   }};search.oninput=draw;draw();return;
  }
  const roles=['admin','clinician','nurse','pharmacist','reception','billing','patient'].map(r=>[r,r]);
  const fields=[{name:'username'},{name:'password',type:'password'},{name:'role',options:roles},{name:'patient_id',type:'number',required:false,label:'Patient ID (patient accounts only)'}];
  if(platform)fields.unshift({name:'hospital_id',options:hospitals.filter(h=>h.active).map(h=>[h.id,h.name])});
  makeForm('Create hospital account',fields,d=>{if(platform)d.hospital_id=Number(d.hospital_id);if(d.patient_id)d.patient_id=Number(d.patient_id);else delete d.patient_id;return api('hospital-users','POST',d)});
  const accounts=await api('hospital-users');
  const draw=()=>{list.replaceChildren();for(const u of accounts.filter(u=>(u.username+' '+u.role+' '+(hospitals.find(h=>h.id===u.hospital_id)?.name||'')).toLowerCase().includes(search.value.toLowerCase()))){
   const card=el('section',undefined,'admin-panel');card.append(el('h3',u.username),el('p',u.role+' · '+(u.active?'Active':'Suspended')+' · '+(hospitals.find(h=>h.id===u.hospital_id)?.name||u.hospital_id)));
   if(u.id!==me.id){const toggle=el('button',u.active?'Suspend account':'Restore account');toggle.onclick=run(async()=>{if(!confirm('Change access for '+u.username+'?'))return;await api('hospital-users','PATCH',{id:u.id,active:!u.active});await managementView(kind)});card.append(toggle)}
   const edit=el('button','Manage role / password');edit.onclick=()=>{makeForm('Manage '+u.username,[{name:'role',options:roles,value:u.role},{name:'password',type:'password',required:false,label:'New password (blank preserves current)'}],d=>{if(!d.password)delete d.password;return api('hospital-users','PATCH',{...d,id:u.id})}).scrollIntoView()};
   const revoke=el('button','Revoke sessions');revoke.onclick=run(async()=>{await api('hospital-users','PATCH',{id:u.id,action:'revoke_sessions'});message.textContent='Sessions revoked for '+u.username});card.append(edit,revoke);list.append(card);
  }};search.oninput=draw;draw();
 }catch(e){message.textContent=e.message}
}

async function portabilityView(){
 module='mobility';$('title').textContent='Patient mobility';$('workspace').hidden=true;$('dashboard').hidden=false;
 const root=$('dashboard');root.replaceChildren(el('h2','Connected patient records'),el('p','Find a patient using their portability code and an active sharing authorization. Other hospitals’ charts are read-only. Add new care under your own hospital’s local patient ID.'));
 const status=el('p');status.setAttribute('role','status');root.append(status);
 const form=(title,fields,submit)=>{
  const box=el('section',undefined,'admin-panel'),f=el('form');box.append(el('h3',title));
  for(const field of fields){const label=el('label',field.label||field.name.replaceAll('_',' '));let input;
   if(field.options){input=el('select');for(const [value,text] of field.options){const o=el('option',text);o.value=value;input.append(o)}}else{input=el('input');input.type=field.type||'text'}
   input.name=field.name;input.required=field.required!==false;if(field.value!==undefined)input.value=field.value;label.append(input);f.append(label);
  }
  const msg=el('p');msg.setAttribute('role','status');const save=el('button','Continue');f.append(msg,save);
  f.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await submit(Object.fromEntries(new FormData(f)));msg.textContent='Completed'}catch(e){msg.textContent=e.message}finally{save.disabled=false}};
  box.append(f);root.append(box);return box;
 };
 const post=d=>api('mobility','POST',d);
 try{
  const [local,directory]=await Promise.all([api('mobility'),api('hospital-directory')]);
  form('Enroll a local patient',[{name:'patient_id',type:'number'}],async d=>{const result=await post({action:'enroll',patient_id:Number(d.patient_id)});status.textContent='Identity '+result.identity_id+' · Portability code: '+result.portability_code+' · Store securely; shown once. Enrollment alone does not authorize another hospital.'});
  const resultArea=el('div');
  form('Find shared patient',[{name:'code',label:'Patient portability code'}],async d=>{
   const result=await post({action:'find',code:d.code});resultArea.replaceChildren();const p=result.profile;
   resultArea.append(el('h3',p.name),el('p','Birth date: '+p.dob+' · Phone: '+p.phone+' · Shared profile version: '+p.version+' · Last updated by hospital '+p.updated_hospital_id));
   const localChart=result.charts.find(c=>c.hospital_id===me.hospital_id);
   if(!localChart){const attach=el('button','Register at my hospital');attach.onclick=async()=>{try{const r=await post({action:'attach',identity_id:p.id});status.textContent='Local patient ID: '+r.patient_id+'. Search again to refresh the shared view.';attach.disabled=true}catch(e){status.textContent=e.message}};resultArea.append(attach)}
   else resultArea.append(el('p','Your local patient ID: '+localChart.patient_id+'. Use the care workspaces to add or edit your hospital’s records.'));
   for(const chart of result.charts){const detail=el('details');detail.append(el('summary',chart.hospital+' · '+(chart.editable?'Your hospital records':'Shared records — read only')),el('pre',JSON.stringify(chart.records,null,2)));resultArea.append(detail)}
   if(localChart&&['admin','clinician','reception'].includes(me.role)){
    const profileForm=form('Update shared demographics',[{name:'name',value:p.name},{name:'dob',type:'date',value:p.dob},{name:'phone',value:p.phone,required:false}],d=>post({...d,action:'profile',identity_id:p.id,version:p.version}));resultArea.append(profileForm);
   }
  });root.append(resultArea);
  const localList=el('section',undefined,'admin-panel');localList.append(el('h3','Your linked patients'));
  for(const p of local){const item=el('p',p.name+' · Identity '+p.id+' · Local patient '+p.patient_id);for(const g of p.outgoing_grants)item.append(el('span',' | Sharing to '+(directory.find(h=>h.id===g.target_hospital_id)?.name||g.target_hospital_id)+': '+(g.active&&g.expires>Date.now()/1000?'active':'inactive/expired')));localList.append(item)}root.append(localList);
  if(['admin','clinician'].includes(me.role)){
   const identities=local.map(p=>[p.id,p.name+' · Local patient '+p.patient_id]);
   const hospitals=directory.filter(h=>h.id!==me.hospital_id).map(h=>[h.id,h.name]);
   form('Authorize sharing of your hospital’s chart',[{name:'identity_id',options:identities},{name:'target_hospital_id',options:hospitals},{name:'consent_reference',label:'Documented patient authorization reference'},{name:'expires',type:'date',label:'Authorization expiry date'}],d=>post({action:'grant',identity_id:Number(d.identity_id),target_hospital_id:Number(d.target_hospital_id),consent_reference:d.consent_reference,expires:Math.floor(new Date(d.expires+'T23:59:59Z').getTime()/1000)}));
   form('Revoke your hospital’s sharing authorization',[{name:'identity_id',options:identities},{name:'target_hospital_id',options:hospitals}],d=>post({action:'revoke',identity_id:Number(d.identity_id),target_hospital_id:Number(d.target_hospital_id)}));
  }
 }catch(e){status.textContent=e.message}
}

async function deviceView(){
 module='devices';$('title').textContent='Medical devices';$('workspace').hidden=true;$('dashboard').hidden=false;
 const root=$('dashboard');root.replaceChildren(el('h2','Device integration hub'),el('p','Register hospital devices or gateways. Incoming readings enter a review queue; they do not silently update patient charts. Ingestion endpoint: /api/device-ingest.'));
 const status=el('p');status.setAttribute('role','status');root.append(status);
 const run=fn=>async()=>{try{await fn()}catch(e){status.textContent=e.message}};
 try{
  if(me.role==='admin'){
   const f=el('form');f.className='admin-panel';
   for(const name of ['name','manufacturer','model']){const label=el('label',name),input=el('input');input.name=name;input.required=name==='name';label.append(input);f.append(label)}
   const label=el('label','Input protocol'),protocol=el('select');protocol.name='protocol';for(const value of ['normalized-json','fhir-observation']){const o=el('option',value);o.value=value;protocol.append(o)}label.append(protocol);f.append(label,el('button','Register device'));
   f.onsubmit=async e=>{e.preventDefault();try{const result=await api('devices','POST',Object.fromEntries(new FormData(f)));status.textContent='Device '+result.id+' · Token (shown once): '+result.token+' · Save securely and refresh to see the device.';f.reset()}catch(e){status.textContent=e.message}};root.append(f);
  }
  const registered=await api('devices');
  for(const device of registered){const card=el('section',undefined,'admin-panel');card.append(el('h3',device.name),el('p',device.protocol+' · '+(device.enabled?'Enabled':'Disabled')+' · Last received: '+(device.last_seen||'Never')));
   if(me.role==='admin'){
    const toggle=el('button',device.enabled?'Disable':'Enable');toggle.onclick=run(async()=>{await api('devices','PATCH',{id:device.id,enabled:!device.enabled});await deviceView()});
    const rotate=el('button','Rotate device token');rotate.onclick=run(async()=>{if(!confirm('Replace this device token? The old token will stop working.'))return;const r=await api('devices','PATCH',{id:device.id,action:'rotate'});status.textContent='New device token (shown once): '+r.token});card.append(toggle,rotate);
   }root.append(card);
  }
  root.append(el('h3','Received observations (latest 500)'));
  const readings=await api('device-readings');
  if(!readings.length)root.append(el('p','No readings received.'));
  for(const r of readings){const card=el('section',undefined,'admin-panel');card.append(el('h4',r.device+' · Local patient '+r.patient_id),el('p',r.code+': '+r.value+' '+r.unit+' · Observed '+r.observed_at+' · '+r.status));
   if(r.status==='pending'){for(const [action,label] of [['accept','Review and add to vitals'],['reject','Reject reading']]){const button=el('button',label);button.onclick=run(async()=>{if(!confirm(label+' for patient '+r.patient_id+'?'))return;await api('device-review','POST',{id:r.id,action});await deviceView()});card.append(button)}}root.append(card);
  }
 }catch(e){status.textContent=e.message}
}

function adminForm(root,title,fields,submit){
 const box=el('section',undefined,'admin-panel'),f=el('form');box.append(el('h3',title));
 for(const field of fields){const label=el('label',field.label||field.name.replaceAll('_',' '));let input;
  if(field.options){input=el('select');for(const [value,text] of field.options){const o=el('option',text);o.value=value;input.append(o)}}
  else{input=el(field.type==='textarea'?'textarea':'input');if(input.tagName==='INPUT')input.type=field.type||'text'}
  input.name=field.name;input.required=field.required!==false;if(field.value!==undefined)input.value=field.value;
  if(field.type==='password'){input.minLength=12;input.autocomplete='new-password'}label.append(input);f.append(label);
 }
 const message=el('p');message.setAttribute('role','status');const save=el('button','Submit');f.append(message,save);
 f.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{const result=await submit(Object.fromEntries(new FormData(f)));message.textContent=typeof result==='string'?result:result?.message||'Saved';}catch(e){message.textContent=e.message}finally{save.disabled=false}};
 box.append(f);root.append(box);return f;
}
function serviceWorkspace(name){closeConsultation();module=name;$('title').textContent=labels[name];$('workspace').hidden=true;$('dashboard').hidden=false;$('dashboard').replaceChildren();return $('dashboard')}
async function registrationView(){
 const root=serviceWorkspace('registrations'),status=el('p');status.setAttribute('role','status');root.append(status);
 try{
  if(me.role==='super_admin'){
   const requests=await api('registration-requests');root.append(el('h2','Hospital onboarding requests'));
   if(!requests.length)root.append(el('p','No registration requests.'));
   for(const r of requests){const card=el('section',undefined,'admin-panel');card.append(el('h3',r.name),el('p',r.contact_name+' · '+r.email+' · '+r.status));
    if(r.status==='pending')for(const action of ['approve','reject']){const b=el('button',action);b.onclick=async()=>{try{b.disabled=true;const response=await api('registration-requests','POST',{id:r.id,action});status.textContent=response.invitation_code?'Hospital '+response.hospital_id+' approved. Admin invitation (shown once): '+response.invitation_code:'Request rejected';}catch(e){status.textContent=e.message;b.disabled=false}};card.append(b)}root.append(card);
   }return;
  }
  const patients=el('button','Register / manage patients');patients.onclick=()=>open('patients');root.append(patients);
  adminForm(root,'Register employee',[{name:'employee_number'},{name:'name'},{name:'email',type:'email'},{name:'department',required:false},{name:'job_title',required:false}],async d=>{const r=await api('employees','POST',d);return 'Employee registered, ID '+r.id+'. Refresh to see the updated roster.'});
  const employees=await api('employees');
  for(const e of employees){const row=el('section',undefined,'admin-panel');row.append(el('h3',e.name),el('p','Employee '+e.id+' · '+e.employee_number+' · '+e.department+' · '+e.job_title+' · '+(e.active?'Active':'Inactive')+' · User '+(e.user_id||'not linked')));
   const edit=el('button','Edit employee');edit.onclick=()=>adminForm(root,'Edit '+e.name,[{name:'name',value:e.name},{name:'email',type:'email',value:e.email},{name:'department',value:e.department,required:false},{name:'job_title',value:e.job_title,required:false},{name:'active',options:[['true','Active'],['false','Inactive']],value:String(Boolean(e.active))}],d=>api('employees','PATCH',{...d,id:e.id,version:e.version,active:d.active==='true'}));row.append(edit);root.append(row);
  }
  adminForm(root,'Invite a staff user or patient',[{name:'role',options:['admin','clinician','nurse','pharmacist','reception','billing','patient'].map(r=>[r,r])},{name:'patient_id',type:'number',required:false,label:'Local patient ID (patient invitations only)'},{name:'employee_id',type:'number',required:false,label:'Employee ID (optional staff link)'}],async d=>{for(const key of ['patient_id','employee_id']){if(d[key])d[key]=Number(d[key]);else delete d[key]}const r=await api('registration-invites','POST',d);return 'Invitation code (shown once, expires in 7 days): '+r.invitation_code});
  for(const i of await api('registration-invites')){const row=el('section',undefined,'admin-panel');row.append(el('p','Invitation '+i.id+' · '+i.role+' · '+(i.used_at?'Used':i.revoked?'Revoked':i.expires<Date.now()/1000?'Expired':'Pending')));
   if(!i.used_at&&!i.revoked){const revoke=el('button','Revoke invitation');revoke.onclick=async()=>{try{await api('registration-invites','PATCH',{id:i.id,revoked:true});await registrationView()}catch(e){status.textContent=e.message}};row.append(revoke)}root.append(row);
  }
 }catch(e){status.textContent=e.message}
}
const publicRegistration=el('details');publicRegistration.append(el('summary','Register a hospital or accept an invitation'));$('login').append(publicRegistration);
adminForm(publicRegistration,'Hospital / practice onboarding request',[{name:'name',label:'Organization name'},{name:'slug',label:'Unique lowercase slug'},{name:'contact_name'},{name:'email',type:'email'}],d=>api('register-hospital','POST',d));
adminForm(publicRegistration,'Accept staff or patient invitation',[{name:'code',label:'Single-use invitation code'},{name:'username'},{name:'password',type:'password'}],d=>api('register-user','POST',d));

function numericField(k){return k.endsWith('_id')||k.endsWith('_cents')||['quantity','reorder_level','authorized_units','used_units','discount_value','usage_limit'].includes(k)}
async function professionalsView(){
 const root=serviceWorkspace('professionals'),message=el('p');message.setAttribute('role','status');root.append(message);
 const admin=me.role==='admin';root.append(el('h2','Your hospital provider directory'));
 const toolbar=el('div'),search=el('input');search.type='search';search.placeholder='Search provider, specialty, license or status';search.setAttribute('aria-label',search.placeholder);toolbar.append(search);
 if(admin){const create=el('button','Register provider');create.onclick=async()=>{await recordView('professionals');await edit(null)};toolbar.append(create)}root.append(toolbar);
 try{
  const profiles=await api('professionals'),list=el('div');root.append(list);
  const draw=()=>{list.replaceChildren();const q=search.value.toLowerCase();for(const profile of profiles.filter(p=>[p.name,p.profession,p.specialty,p.license_number,p.status,p.credential_status].join(' ').toLowerCase().includes(q))){
   const card=el('section',undefined,'admin-panel');card.append(el('h3',profile.name),el('p',pretty(profile.profession)+' · '+(profile.specialty||'Specialty not recorded')+' · '+profile.status),el('p','License: '+(profile.license_number||'Not recorded')+' · '+(profile.license_jurisdiction||'Jurisdiction not recorded')+' · Expiry: '+(profile.license_expiry||'Not recorded')),el('p','Credentials: '+(profile.credential_status||'unverified')+' · Staff account: '+(profile.user_id?'Linked':'Not registered')));
   if(admin){const editButton=el('button','Edit profile');editButton.onclick=async()=>{await recordView('professionals');await edit(profile)};card.append(editButton);
    for(const [action,label] of [['review','Review credentials'],['invite','Create account invitation'],['activate','Activate / restore'],['deactivate','Deactivate'],['suspend','Suspend']]){
     if(action==='invite'&&(profile.user_id||profile.status!=='inactive'))continue;
     const b=el('button',label);b.onclick=async()=>{try{
      if(action==='review'){adminForm(card,'Record credential review',[{name:'review_reference',label:'Evidence / credential review reference'}],async d=>{await api('provider-management','PATCH',{...d,id:profile.id,version:profile.version,action});await professionalsView();return 'Credential review saved'});return}
      if(!confirm(label+' for '+profile.name+'? Activation restores the linked staff login; suspension/deactivation revokes its access.'))return;
      const result=await api('provider-management','PATCH',{id:profile.id,version:profile.version,action});
      if(result.invitation_code)message.textContent='Provider account invitation (shown once): '+result.invitation_code;
      else await professionalsView();
     }catch(e){message.textContent=e.message}};card.append(b)
    }
   }list.append(card)
  }if(!list.children.length)list.append(el('p','No providers match. Hospital admins can register a provider or review an application.'))};search.oninput=draw;draw();
  if(admin){root.append(el('h2','Provider applications'));
   for(const application of await api('provider-applications')){const card=el('section',undefined,'admin-panel');card.append(el('h3',application.name+' · '+pretty(application.profession)),el('p',application.email+' · '+application.specialty+' · '+application.status),el('p','License '+application.license_number+' · '+application.license_jurisdiction+' · Expires '+application.license_expiry));
    if(application.status==='pending')adminForm(card,'Review application',[{name:'action',options:[['approve','Approve and create invitation'],['reject','Reject']]},{name:'review_reference',label:'Credential evidence / review decision reference'}],async d=>{const result=await api('provider-applications','POST',{...d,id:application.id});return result.invitation_code?'Approved. Provider invitation (shown once): '+result.invitation_code+' · Refresh after registration to activate.':'Application rejected'});root.append(card)
   }
  }
 }catch(e){message.textContent=e.message}
}
async function knowledgeView(){
 const root=serviceWorkspace('knowledge');root.append(el('h2','Clinical knowledge & peer support'));
 for(const [label,destination] of [['Search knowledge articles','knowledge_articles'],['Ask the care team / review requests','staff_requests'],['Alerts & escalation','alerts'],['AI knowledge assistance','ai']]){const b=el('button',label);b.onclick=()=>open(destination);root.append(b)}
 root.append(el('p','Use your hospital’s emergency escalation channel for immediate help. Staff requests and alerts are work queues, not a continuously monitored emergency service.'));
 try{const articles=await api('knowledge_articles');const search=el('input');search.type='search';search.placeholder='Search titles, categories and article text';search.setAttribute('aria-label',search.placeholder);const list=el('div');root.append(search,list);
  const draw=()=>{list.replaceChildren();for(const article of articles.filter(a=>(a.title+' '+a.category+' '+a.content).toLowerCase().includes(search.value.toLowerCase()))){const d=el('details');d.className='admin-panel';d.append(el('summary',article.title+' · '+article.status),el('p',article.content),el('p','Reviewer: '+(article.reviewed_by||'Not yet reviewed')));if(article.source_url?.startsWith('https://')){const a=el('a','Source reference');a.href=article.source_url;a.target='_blank';a.rel='noopener noreferrer';d.append(a)}list.append(d)}};search.oninput=draw;draw();
 }catch(e){root.append(el('p',e.message))}
}
async function aiView(){
 const root=serviceWorkspace('ai');root.append(el('h2','AI knowledge assistance'),el('p','For general clinical education and hospital knowledge navigation. Do not enter patient identifiers, charts or private patient data. Review every response independently.'));
 try{const configuration=await api('ai-status');root.append(el('p','Hospital permission: '+(configuration.enabled?'Enabled':'Disabled')+' · Provider: '+(configuration.configured?'Configured':'Not configured')));
  if(!configuration.enabled||!configuration.configured)return;
  const output=el('section');
  const f=adminForm(root,'Ask a knowledge question',[{name:'question',type:'textarea'}],async d=>{if(!confirm('Confirm this question contains no patient identifiers or private patient data.'))throw Error('Confirmation required');const result=await api('ai-assist','POST',{...d,confirm_no_patient_identifiers:true});output.replaceChildren(el('h3','Draft — clinician review required'),el('p',result.answer),el('p',result.notice));for(const s of result.sources)output.append(el('p','[KB:'+s.id+'] '+s.title+' · '+(s.source_url||'Hospital knowledge article')));return 'Draft generated; no chart was changed.'});f.elements.question.maxLength=2000;root.append(output);
 }catch(e){root.append(el('p',e.message))}
}
let activeConsultation=null;
function closeConsultation(){if(activeConsultation){clearInterval(activeConsultation.timer);activeConsultation.pc?.close();for(const track of activeConsultation.stream?.getTracks()||[])track.stop();for(const track of activeConsultation.screen?.getTracks()||[])track.stop();activeConsultation=null}}
window.addEventListener('beforeunload',closeConsultation);
async function telemedicineView(){
 const root=serviceWorkspace('telemedicine'),status=el('p');status.setAttribute('role','status');root.append(status);
 try{
  const providers=await api('telemedicine-providers');
  const fields=[{name:'provider_id',options:providers.map(p=>[p.id,p.username+' · '+p.role])},{name:'scheduled_at',type:'datetime-local'},{name:'reason',type:'textarea'},{name:'mode',options:['video','audio','chat'].map(m=>[m,m])}];
  if(me.role!=='patient')fields.unshift({name:'patient_id',type:'number'});
  adminForm(root,'Schedule consultation',fields,async d=>{if(d.patient_id)d.patient_id=Number(d.patient_id);d.provider_id=Number(d.provider_id);d.scheduled_at=new Date(d.scheduled_at).toISOString();const r=await api('telemedicine','POST',d);return 'Visit '+r.id+' scheduled. Refresh to see it.'});
  for(const visit of await api('telemedicine')){
   const card=el('section',undefined,'admin-panel');card.append(el('h3','Visit '+visit.id+' · Patient '+visit.patient_id),el('p',visit.scheduled_at+' · '+visit.mode+' · '+visit.status),el('p',visit.reason));
   if(!['completed','cancelled'].includes(visit.status)){
    adminForm(card,'Record patient consent',[{name:'consent_reference',label:'Consent statement / documented authorization'}],d=>api('telemedicine','PATCH',{...d,id:visit.id,action:'consent'}));
    const transitions={scheduled:['waiting','cancelled'],waiting:['in-progress','cancelled'],'in-progress':['completed','cancelled']};
    for(const state of (transitions[visit.status]||[]).filter(s=>me.role!=='patient'||['waiting','cancelled'].includes(s))){const b=el('button',state);b.onclick=async()=>{try{await api('telemedicine','PATCH',{id:visit.id,action:'status',status:state,version:visit.version});await telemedicineView()}catch(e){status.textContent=e.message}};card.append(b)}
    if(visit.provider_id===me.id||me.role==='patient'){const join=el('button','Open secure consultation');join.onclick=async()=>{try{await consultationRoom(visit,card)}catch(e){status.textContent=e.message}};card.append(join)}
   }root.append(card);
  }
 }catch(e){status.textContent=e.message}
}
async function consultationRoom(visit,parent){
 closeConsultation();const initial=await api('telemedicine-events?visit_id='+visit.id+'&since=0');
 const room=el('section',undefined,'consultation');room.append(el('h3','Consultation '+visit.id),el('p',initial.relay_configured?'TURN relay configured':'TURN relay not configured. Video/audio may fail across some networks; authenticated visit chat is available.'));
 const message=el('p');message.setAttribute('role','status');const log=el('div');log.setAttribute('aria-live','polite');room.append(message,log);parent.append(room);
 const state={pc:null,stream:null,screen:null,timer:null,since:0,polling:false,pending:[]};activeConsultation=state;
 const send=(kind,payload)=>api('telemedicine-events','POST',{visit_id:visit.id,kind,payload});
 adminForm(room,'Consultation chat',[{name:'message',type:'textarea'}],async d=>{await send('chat',d.message);return 'Message sent'});
 let local,remote;
 const start=el('button',visit.mode==='chat'?'Chat visit':'Enable camera / microphone');start.disabled=visit.mode==='chat';
 start.onclick=async()=>{try{
  if(state.pc)return;
  state.stream=await navigator.mediaDevices.getUserMedia({video:visit.mode==='video',audio:true});
  local=el('video');local.autoplay=true;local.muted=true;local.playsInline=true;local.srcObject=state.stream;
  remote=el('video');remote.autoplay=true;remote.playsInline=true;room.append(local,remote);
  state.pc=new RTCPeerConnection({iceServers:initial.ice_servers});for(const track of state.stream.getTracks())state.pc.addTrack(track,state.stream);
  state.pc.ontrack=e=>{remote.srcObject=e.streams[0]};state.pc.onicecandidate=e=>{if(e.candidate)send('candidate',e.candidate.toJSON()).catch(e=>message.textContent=e.message)};
  state.pc.onconnectionstatechange=()=>{message.textContent='Media connection: '+state.pc.connectionState};
  if(visit.provider_id===me.id){await state.pc.setLocalDescription(await state.pc.createOffer());await send('offer',state.pc.localDescription.toJSON())}
  // Re-read retained signaling when the patient enables media after the provider's offer.
  state.since=0;start.disabled=true;
 }catch(e){message.textContent=e.message;state.pc?.close();state.pc=null;for(const t of state.stream?.getTracks()||[])t.stop()}};
 const mute=el('button','Mute / unmute microphone');mute.onclick=()=>{for(const t of state.stream?.getAudioTracks()||[])t.enabled=!t.enabled};
 const camera=el('button','Camera on / off');camera.onclick=()=>{for(const t of state.stream?.getVideoTracks()||[])t.enabled=!t.enabled};
 const screen=el('button','Share screen');screen.onclick=async()=>{try{const sender=state.pc?.getSenders().find(s=>s.track?.kind==='video');if(!sender)throw Error('Enable a video visit first');state.screen=await navigator.mediaDevices.getDisplayMedia({video:true});const track=state.screen.getVideoTracks()[0];await sender.replaceTrack(track);track.onended=()=>sender.replaceTrack(state.stream.getVideoTracks()[0])}catch(e){message.textContent=e.message}};
 const leave=el('button','Leave consultation');leave.onclick=()=>{send('leave',{}).catch(()=>{});closeConsultation();room.remove()};room.append(start,mute,camera,screen,leave);
 const poll=async()=>{if(state.polling||activeConsultation!==state)return;state.polling=true;try{
  const result=await api('telemedicine-events?visit_id='+visit.id+'&since='+state.since);
  for(const event of result.events){state.since=Math.max(state.since,event.id);if(event.kind==='chat'){if(!log.querySelector('[data-event="'+event.id+'"]')){const p=el('p','User '+event.user_id+': '+event.payload);p.dataset.event=event.id;log.append(p)}continue}if(event.user_id===me.id)continue;
   if(event.kind==='leave')message.textContent='Other participant left the consultation.';
   if(!state.pc)continue;
   if(event.kind==='offer'&&me.role==='patient'){await state.pc.setRemoteDescription(event.payload);await state.pc.setLocalDescription(await state.pc.createAnswer());await send('answer',state.pc.localDescription.toJSON())}
   if(event.kind==='answer'&&visit.provider_id===me.id&&state.pc.signalingState==='have-local-offer')await state.pc.setRemoteDescription(event.payload);
   if(event.kind==='candidate'){if(state.pc.remoteDescription)await state.pc.addIceCandidate(event.payload);else state.pending.push(event.payload)}
   if(state.pc.remoteDescription)while(state.pending.length)await state.pc.addIceCandidate(state.pending.shift());
  }
 }catch(e){message.textContent=e.message;closeConsultation()}finally{state.polling=false}};
 await poll();state.timer=setInterval(poll,2000);
}

function pretty(value){return value.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase())}
function currentLocalTime(){const now=new Date();return new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,16)}
async function chartingView(kind){
 const root=serviceWorkspace(kind),notice=el('p');notice.setAttribute('role','status');root.append(notice);
 const shortcuts=el('div');for(const [label,name] of [['My Patients / roster','rosters'],['Vital signs','vitals'],['Medication records','administrations'],['Care plans','care_plans'],['Orders','orders'],['Results','results'],['Staff aid','knowledge']]){if(me.modules.includes(name)||['rosters','knowledge'].includes(name)){const b=el('button',label);b.onclick=()=>open(name);shortcuts.append(b)}}root.append(shortcuts);
 try{
  const [config,patients,shifts]=await Promise.all([api('ward-config'),api('patients'),api('duty-shifts')]);
  const assignmentIds=new Set(shifts.filter(s=>s.staff_id===me.id&&['scheduled','checked-in'].includes(s.attendance)).flatMap(s=>s.patients.map(p=>p.id)));
  const label=el('label','Patient chart'),select=el('select');label.append(select);root.append(label);
  const placeholder=el('option','Select patient');placeholder.value='';select.append(placeholder);
  for(const p of [...patients].sort((a,b)=>Number(assignmentIds.has(b.id))-Number(assignmentIds.has(a.id)))){const option=el('option',(assignmentIds.has(p.id)?'Assigned · ':'')+p.name+' · MRN '+p.mrn+' · ID '+p.id);option.value=p.id;select.append(option)}
  const content=el('div');root.append(content);
  const nursingKeys=['shift_assessment','vital_signs','pain_assessment','medication_administration','intake_output','nursing_care_plan','wound_skin','devices_lines','mobility_safety','patient_education','nursing_progress','nursing_handover','nursing_discharge_transfer'];
  const templates=Object.fromEntries(Object.entries(config.templates).filter(([key])=>kind==='nursing'?nursingKeys.includes(key):!nursingKeys.includes(key)));
  let patientId;
  const entryForm=(type,prior=null,correction=false,editing=false)=>{
   const host=el('section');content.prepend(host);
   const fields=[{name:'care_at',type:'datetime-local',value:editing?toLocalDateInput(prior.care_at):currentLocalTime(),label:'Actual time of care (your local timezone)'}];
   for(const key of templates[type])fields.push({name:key,type:'textarea',required:false,value:prior?.fields[key]||'',label:pretty(key)});
   if(correction)fields.push({name:'correction_reason',type:'textarea',label:'Reason for correction / addendum'});
   const f=adminForm(host,(editing?'Edit draft':correction?'Linked correction':'New draft')+' · '+pretty(type),fields,async data=>{
    const care_at=new Date(data.care_at).toISOString(),reason=data.correction_reason;delete data.care_at;delete data.correction_reason;
    if(editing)await api('clinical-entries','PATCH',{id:prior.id,version:prior.version,action:'edit',fields:data,care_at});
    else{const body={patient_id:patientId,entry_type:type,fields:data,care_at};if(correction){body.correction_of=prior.id;body.correction_reason=reason}await api('clinical-entries','POST',body)}
    await load();return 'Draft saved. Review before signing.';
   });
   const cancel=el('button','Cancel');cancel.type='button';cancel.onclick=()=>host.remove();f.append(cancel);host.scrollIntoView({block:'start'});
  };
  const load=async()=>{
   content.replaceChildren();if(!select.value)return;patientId=Number(select.value);
   content.append(el('h2',patients.find(p=>p.id===patientId)?.name||'Patient chart'),el('p','Blank fields remain unrecorded. Save drafts, then explicitly sign. Corrections retain the original signed entry.'));
   const tools=el('div');for(const type of Object.keys(templates)){const b=el('button',pretty(type));b.onclick=()=>entryForm(type);tools.append(b)}content.append(tools);
   const entries=await api('clinical-entries?patient_id='+patientId);
   for(const entry of entries){const card=el('section',undefined,'admin-panel');card.append(el('h3',pretty(entry.entry_type)+' · '+entry.status),el('p','Author: '+entry.author+' · Care time: '+new Date(entry.care_at).toLocaleString()+' · Signed: '+(entry.signed_at?new Date(entry.signed_at).toLocaleString():'Not signed')));
    if(entry.correction_of)card.append(el('p','Correction of entry '+entry.correction_of+' · '+entry.correction_reason));
    for(const [key,value] of Object.entries(entry.fields))if(value)card.append(el('h4',pretty(key)),el('p',value));
    if(entry.status==='draft'&&entry.author_id===me.id&&templates[entry.entry_type]){
     const edit=el('button','Edit draft');edit.onclick=()=>entryForm(entry.entry_type,entry,false,true);
     const sign=el('button','Review & sign');sign.onclick=async()=>{try{if(!confirm('Sign this entry as '+me.username+'? Verify the patient, care time and every observation. Signed entries cannot be overwritten.'))return;await api('clinical-entries','PATCH',{id:entry.id,version:entry.version,action:'sign',confirm:true});await load()}catch(e){notice.textContent=e.message}};card.append(edit,sign);
    }
    if(entry.status==='signed'&&templates[entry.entry_type]){const correct=el('button','Add correction / addendum');correct.onclick=()=>entryForm(entry.entry_type,entry,true);const copy=el('button','Use as a new draft');copy.onclick=()=>{if(confirm('Review every copied field for the current assessment. This creates an unsigned draft only.'))entryForm(entry.entry_type,entry)};card.append(correct,copy)}content.append(card);
   }
  };
  select.onchange=()=>load().catch(e=>notice.textContent=e.message);
  const aiSection=el('details');aiSection.append(el('summary','Organize a de-identified draft with AI'));
  adminForm(aiSection,'Draft organizer — no patient identifiers',[{name:'draft',type:'textarea'}],async d=>{if(!confirm('Confirm this text has no patient identifiers or private patient data. AI must not add facts.'))throw Error('Confirmation required');const r=await api('ward-ai','POST',{...d,confirm_no_patient_identifiers:true});const result=el('section');result.append(el('h4','Review-only draft; not saved'),el('p',r.draft));aiSection.append(result);return 'Review and manually copy only verified content. No chart was changed.'});root.append(aiSection);
 }catch(e){notice.textContent=e.message}
}
async function rosterView(kind){
 const root=serviceWorkspace(kind),notice=el('p');notice.setAttribute('role','status');root.append(notice);
 try{
  const [config,localPatients,chartEntries]=await Promise.all([api('ward-config'),api('patients'),api('clinical-entries')]);const admin=me.role==='admin';
  const range=el('div'),dateInput=el('input');dateInput.type='date';dateInput.value=currentLocalTime().slice(0,10);dateInput.setAttribute('aria-label','Roster start date');range.append(dateInput);
  const list=el('div');let shifts=[];let days=1;
  const reload=async()=>{const begin=new Date(dateInput.value+'T00:00:00'),end=new Date(begin);if(days===31){end.setMonth(end.getMonth()+1);end.setDate(end.getDate()-1)}else end.setDate(end.getDate()+days-1);end.setHours(23,59,59,999);shifts=await api('duty-shifts?from='+encodeURIComponent(begin.toISOString())+'&to='+encodeURIComponent(end.toISOString()));draw()};
  for(const [label,count] of [['Daily roster',1],['Weekly roster',7],['Monthly roster',31]]){const b=el('button',label);b.onclick=()=>{days=count;reload().catch(e=>notice.textContent=e.message)};range.append(b)}dateInput.onchange=()=>reload().catch(e=>notice.textContent=e.message);root.append(range,list);
  const draw=()=>{list.replaceChildren();if(!shifts.length)list.append(el('p','No shifts in this period.'));
   for(const shift of shifts){const card=el('section',undefined,'admin-panel');card.append(el('h3',shift.staff+' · '+shift.role+' · '+shift.shift_name),el('p',shift.department+' · '+new Date(shift.starts_at).toLocaleString()+' → '+new Date(shift.ends_at).toLocaleString()),el('p','Responsibility: '+(shift.responsibility||'Not set')+' · On call: '+shift.on_call+' · Attendance: '+shift.attendance+' · Handover: '+shift.handover),el('p','Assigned patients: '+(shift.patients.map(p=>p.name+' (#'+p.id+')').join(', ')||'None')));
    const action=(label,body)=>{const b=el('button',label);b.onclick=async()=>{try{await api('duty-shifts','PATCH',{id:shift.id,version:shift.version,...body});await reload()}catch(e){notice.textContent=e.message}};card.append(b)};
    if(shift.staff_id===me.id){if(shift.attendance==='scheduled'){action('Clock in',{action:'clock-in'});action('Report absence',{action:'absence'})}if(shift.attendance==='checked-in')action('Clock out',{action:'clock-out'});
     adminForm(card,'Complete handover after signing each patient handover',[{name:'entry_id',options:chartEntries.filter(e=>e.author_id===me.id&&e.status==='signed'&&['nursing_handover','clinical_handover'].includes(e.entry_type)&&shift.patients.some(p=>p.id===e.patient_id)).map(e=>[e.id,pretty(e.entry_type)+' · '+(localPatients.find(p=>p.id===e.patient_id)?.name||'Patient')+' · '+new Date(e.care_at).toLocaleString()]),label:'Signed patient handover'}],async d=>{await api('duty-shifts','PATCH',{id:shift.id,version:shift.version,action:'handover',entry_id:Number(d.entry_id)});await reload();return 'Handover completed'});
     if(shift.attendance==='scheduled'){const swap=el('button','Request a shift swap');swap.onclick=async()=>{try{const options=await api('swap-options?shift_id='+shift.id);adminForm(card,'Choose colleague’s shift',[{name:'target_shift_id',options:options.map(s=>[s.id,s.username+' · '+s.starts_at+' · '+s.department])}],d=>api('shift-swaps','POST',{shift_id:shift.id,target_shift_id:Number(d.target_shift_id)}))}catch(e){notice.textContent=e.message}};card.append(swap)}
    }
    if(admin){adminForm(card,'Assign / unassign a local patient',[{name:'patient_id',options:localPatients.map(p=>[p.id,p.name+' · '+p.mrn])},{name:'action',options:[['assign','Assign'],['unassign','Unassign']]}],async d=>{await api('shift-patients','POST',{...d,shift_id:shift.id,patient_id:Number(d.patient_id)});await reload();return 'Assignment updated'});
     const replacement=el('button','Find replacement');replacement.onclick=async()=>{try{const report=await api('coverage?shift_id='+shift.id);adminForm(card,'Approve replacement',[{name:'replacement_id',options:report.replacements.map(p=>[p.id,p.username+' · '+p.role])}],async d=>{await api('duty-shifts','PATCH',{id:shift.id,version:shift.version,action:'replace',replacement_id:Number(d.replacement_id)});await reload();return 'Replacement assigned'})}catch(e){notice.textContent=e.message}};card.append(replacement);
    }list.append(card);
   }
  };await reload();
  if(admin){adminForm(root,'Assign shift',[{name:'staff_id',options:config.staff.map(s=>[s.id,s.username+' · '+s.role])},{name:'department'},{name:'shift_name'},{name:'starts_at',type:'datetime-local'},{name:'ends_at',type:'datetime-local'},{name:'responsibility',required:false},{name:'on_call',options:['none','primary','backup'].map(x=>[x,x])},{name:'supervisor_id',options:[['','Not assigned'],...config.staff.map(s=>[s.id,s.username])],required:false},{name:'covering_id',options:[['','Not assigned'],...config.staff.map(s=>[s.id,s.username])],required:false}],async d=>{d.staff_id=Number(d.staff_id);for(const k of ['supervisor_id','covering_id']){if(d[k])d[k]=Number(d[k]);else delete d[k]}for(const k of ['starts_at','ends_at'])d[k]=new Date(d[k]).toISOString();await api('duty-shifts','POST',d);await reload();return 'Shift assigned'});
   const report=await api('coverage');const summary=el('section',undefined,'admin-panel');summary.append(el('h3','Supervisor coverage'),el('p','Active shifts: '+report.active_shifts.length+' · Unassigned inpatients: '+report.unassigned_inpatients.length+' · Overlaps: '+report.overlapping_shifts.length+' · Pending handovers: '+report.pending_handovers.length),el('pre',JSON.stringify(report,null,2)));root.append(summary);
  }else{adminForm(root,'Request leave',[{name:'starts_at',type:'datetime-local'},{name:'ends_at',type:'datetime-local'},{name:'reason',type:'textarea'}],d=>{for(const k of ['starts_at','ends_at'])d[k]=new Date(d[k]).toISOString();return api('staff-leave','POST',d)})}
  for(const request of await api('staff-leave')){const card=el('section',undefined,'admin-panel');card.append(el('p','Leave '+request.id+' · Staff '+request.staff_id+' · '+request.starts_at+' → '+request.ends_at+' · '+request.status));if(admin&&request.status==='pending')for(const state of ['approved','rejected']){const b=el('button',state);b.onclick=async()=>{try{await api('staff-leave','PATCH',{id:request.id,status:state});await rosterView(kind)}catch(e){notice.textContent=e.message}};card.append(b)}root.append(card)}
  for(const swap of await api('shift-swaps')){const card=el('section',undefined,'admin-panel');card.append(el('p','Swap '+swap.id+' · Shifts '+swap.shift_id+' ↔ '+swap.target_shift_id+' · '+swap.status));const actions=[];if(swap.status==='requested'&&swap.target_id===me.id)actions.push('accept');if(admin&&swap.status==='accepted')actions.push('approve');if(['requested','accepted'].includes(swap.status))actions.push('reject');for(const action of actions){const b=el('button',action);b.onclick=async()=>{try{await api('shift-swaps','PATCH',{id:swap.id,action});await rosterView(kind)}catch(e){notice.textContent=e.message}};card.append(b)}root.append(card)}
 }catch(e){notice.textContent=e.message}
}

function renderNavigation(modules){
 const nav=$('nav');nav.replaceChildren();const home=el('button','Overview');home.onclick=overview;nav.append(home);
 const groups=[
  ['Care & charting',['safety','critical_results','referral_followups','medication_reviews','transition_tasks','safety_events','nursing','doctor','patients','encounters','notes','allergies','medications','vitals','orders','results','care_plans','referrals','prescriptions','administrations','specialty_cases','outreach','documents','immunizations','history','care_team','mobility']],
  ['Daily operations',['appointments','beds','inventory','messages','workqueues','devices','alerts','telemedicine']],
  ['People & schedules',['professionals','availability','rosters','attendance','coverage','staff_requests','knowledge','knowledge_articles','ai']],
  ['Finance & assistance',['invoices','payments','payers','policies','authorizations','claims','remittances','charities','sponsorships','coupons','coupon_redemptions']],
  ['Administration',['hospitals','registrations','hospital-users','audit','tenant-audit']]
 ];
 const rendered=new Set();for(const [title,names] of groups){const shown=names.filter(m=>modules.includes(m));if(!shown.length)continue;nav.append(el('p',title,'nav-section'));for(const m of shown){const button=el('button',labels[m]||pretty(m));button.dataset.module=m;button.onclick=()=>open(m);nav.append(button);rendered.add(m)}}
 for(const m of modules.filter(m=>!rendered.has(m))){const b=el('button',labels[m]||pretty(m));b.dataset.module=m;b.onclick=()=>open(m);nav.append(b)}
}

function toLocalDateInput(value){const date=new Date(value);return Number.isNaN(date.getTime())?'':new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16)}

async function safetyView(){
 const root=serviceWorkspace('safety');root.append(el('h2','Close the loop on outstanding care'),el('p','Each queue has a local owner and a traceable outcome. Use established emergency channels for immediate clinical help.'));
 try{const report=await api('safety-overview'),grid=el('div',undefined,'cards');root.append(grid);
  for(const [name,count] of Object.entries(report.pending)){if(name==='device_readings'&&!['admin','clinician','nurse'].includes(me.role))continue;const b=el('button',undefined,'card');b.append(el('span',labels[name]||pretty(name)),el('strong',String(count)),el('small','Open review queue →'));b.onclick=()=>open(name==='device_readings'?'devices':name);grid.append(b)}
  const quality=el('section',undefined,'admin-panel');quality.append(el('h3','Patient identity review candidates'),el('p',report.notice));
  for(const candidate of report.identity_review_candidates)quality.append(el('p',candidate.normalized_name+' · DOB '+candidate.dob+' · '+candidate.records+' local records. Review identity; no automatic merge.'));
  if(!report.identity_review_candidates.length)quality.append(el('p','No duplicate name/date-of-birth candidates in this check.'));root.append(quality);
 }catch(e){root.append(el('p',e.message))}
}

adminForm(publicRegistration,'Apply as a healthcare provider',[
 {name:'hospital_slug',label:'Hospital / practice registration code'},
 {name:'name',label:'Full professional name'},{name:'email',type:'email'},{name:'phone'},
 {name:'profession',options:['doctor','nurse','pharmacist','dentist','therapist','allied_health'].map(p=>[p,pretty(p)])},
 {name:'specialty'},{name:'license_number'},{name:'license_jurisdiction'},{name:'license_expiry',type:'date'}
],d=>api('provider-registration','POST',d));
