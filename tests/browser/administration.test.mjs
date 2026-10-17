import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
const html=await readFile(new URL('../../static/index.html',import.meta.url),'utf8');
const source=await readFile(new URL('../../static/app.js',import.meta.url),'utf8');
async function fixture(role){
 const dom=new JSDOM(html,{url:'https://olamidemedical.health',runScripts:'outside-only'}),w=dom.window,calls=[];
 w.HTMLElement.prototype.scrollIntoView=()=>{};w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.confirm=()=>true;
 const user={id:7,username:'operator',role,hospital_id:role==='super_admin'?null:1,hospital:role==='super_admin'?null:{id:1,name:'Hospital A'},modules:['patients','appointments'],schema:{appointments:['patient_id','provider','department','scheduled_at','reason','status']},states:{appointments:['scheduled','completed']}};
 w.fetch=async(path,opts={})=>{calls.push({path,opts});let data;
  if(path==='/api/me')data=user;
  else if(path==='/api/patients')data=[{id:1,name:'Synthetic Patient',mrn:'TEST1',dob:'1990-01-01'}];
  else if(path==='/api/ward-config')data={templates:{shift_assessment:['condition','observations']},staff:[{id:8,username:'nurseone',role:'nurse'}]};
  else if(path==='/api/safety-overview')data={pending:{critical_results:2,transition_tasks:1},identity_review_candidates:[],notice:'Operational review only'};
  else if(path==='/api/coverage')data={active_shifts:[],unassigned_inpatients:[],overlapping_shifts:[],pending_handovers:[],replacements:[]};
  else if(path.startsWith('/api/clinical-entries'))data=opts.method==='POST'?{id:1}:[];
  else if(path==='/api/hospitals')data=[{id:1,name:'Hospital A',slug:'a',active:1,version:1,users:2,patients:1}];
  else if(path==='/api/hospital-users')data=opts.method==='POST'?{id:12}:[];
  else if(path==='/api/devices')data=opts.method==='POST'?{id:1,token:'synthetic-device-token'}:[];
  else if(path==='/api/hospital-directory')data=[{id:1,name:'Hospital A'},{id:2,name:'Hospital B'}];
  else if(path==='/api/mobility')data=opts.method==='POST'?{ok:true}:[{id:3,name:'Synthetic patient',patient_id:4,outgoing_grants:[]}];
  else data=[];
  return {ok:true,status:200,json:async()=>data};
 };
 w.eval(source+'\nwindow.testing={managementView,portabilityView,deviceView,chartingView,rosterView,recordView,edit,safetyView,professionalsView};');
 await new Promise(r=>setTimeout(r,25));return {dom,w,calls};
}
test('platform administrator sees hospital controls and staff creation sends selected tenant',async()=>{
 const {dom,w,calls}=await fixture('super_admin');try{
  assert.match(w.document.getElementById('nav').textContent,/Hospital administration/);
  assert.doesNotMatch(w.document.getElementById('nav').textContent,/Patient mobility|Medical devices/);
  await w.testing.managementView('hospital-users');const f=w.document.querySelector('#dashboard form');
  f.elements.username.value='newadmin';f.elements.password.value='synthetic-password-123';
  f.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,25));
  const call=calls.find(x=>x.path==='/api/hospital-users'&&x.opts.method==='POST');assert.ok(call);
  assert.equal(JSON.parse(call.opts.body).hospital_id,1);assert.equal(call.opts.headers['X-Requested-With'],'OlamideMedical');
 }finally{dom.window.close();}
});
test('hospital administrator has portability grants and device registration connected to API',async()=>{
 const {dom,w,calls}=await fixture('admin');try{
  assert.match(w.document.getElementById('nav').textContent,/Patient mobility/);
  await w.testing.portabilityView();assert.match(w.document.getElementById('dashboard').textContent,/Authorize sharing/);
  const f=[...w.document.querySelectorAll('#dashboard form')].find(f=>f.elements.consent_reference);
  f.elements.consent_reference.value='Synthetic consent';f.elements.expires.value='2026-11-01';
  f.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,25));
  const grant=calls.find(x=>x.path==='/api/mobility'&&x.opts.method==='POST');assert.equal(JSON.parse(grant.opts.body).target_hospital_id,2);
  await w.testing.deviceView();const device=w.document.querySelector('#dashboard form');device.elements.name.value='Test monitor';
  device.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,25));
  assert.match(w.document.getElementById('dashboard').textContent,/synthetic-device-token/);
  assert.ok(calls.find(x=>x.path==='/api/devices'&&x.opts.method==='POST'));
 }finally{dom.window.close();}
});

test('nursing patient template saves a structured draft to the clinical backend',async()=>{
 const {dom,w,calls}=await fixture('nurse');try{
  await w.testing.chartingView('nursing');
  const select=w.document.querySelector('#dashboard select');select.value='1';select.dispatchEvent(new w.Event('change'));
  await new Promise(r=>setTimeout(r,20));
  const button=[...w.document.querySelectorAll('#dashboard button')].find(b=>b.textContent==='Shift Assessment');assert.ok(button);button.click();
  const form=[...w.document.querySelectorAll('#dashboard form')].find(f=>f.elements.condition);assert.ok(form);
  form.elements.condition.value='Synthetic observed condition';
  form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,20));
  const call=calls.find(c=>c.path==='/api/clinical-entries'&&c.opts.method==='POST');assert.ok(call);
  const payload=JSON.parse(call.opts.body);assert.equal(payload.patient_id,1);assert.equal(payload.entry_type,'shift_assessment');assert.equal(payload.fields.condition,'Synthetic observed condition');assert.ok(payload.care_at.endsWith('Z'));
 }finally{dom.window.close();}
});
test('record editor uses a named patient selector and supervisor roster submits timezone-aware shifts',async()=>{
 const {dom,w,calls}=await fixture('admin');try{
  await w.testing.recordView('appointments');await w.testing.edit(null);
  const patient=w.document.getElementById('recordform').elements.patient_id;assert.equal(patient.tagName,'SELECT');assert.match(patient.textContent,/Synthetic Patient/);
  w.document.getElementById('editor').close();await w.testing.rosterView('rosters');
  const form=[...w.document.querySelectorAll('#dashboard form')].find(f=>f.elements.shift_name);assert.ok(form);
  form.elements.department.value='Ward A';form.elements.shift_name.value='Morning';form.elements.starts_at.value='2026-11-01T07:00';form.elements.ends_at.value='2026-11-01T15:00';
  form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,20));
  const call=calls.find(c=>c.path==='/api/duty-shifts'&&c.opts.method==='POST');assert.ok(call);const payload=JSON.parse(call.opts.body);assert.equal(payload.staff_id,8);assert.ok(payload.starts_at.endsWith('Z'));
 }finally{dom.window.close();}
});

test('safety command center opens the real source-linked review queue',async()=>{
 const {dom,w,calls}=await fixture('admin');try{
  await w.testing.safetyView();const button=[...w.document.querySelectorAll('#dashboard button')].find(b=>b.textContent.includes('Critical result acknowledgment'));assert.ok(button);button.click();
  await new Promise(r=>setTimeout(r,20));assert.ok(calls.find(c=>c.path==='/api/critical_results'));assert.equal(w.document.getElementById('title').textContent,'Critical result acknowledgment');
 }finally{dom.window.close();}
});

test('provider registration submits credentials for hospital review without granting a client-chosen role',async()=>{
 const {dom,w,calls}=await fixture('admin');try{
  const form=[...w.document.querySelectorAll('form')].find(f=>f.elements.hospital_slug);assert.ok(form);
  for(const [key,value] of Object.entries({hospital_slug:'existing-hospital',name:'Synthetic Provider',email:'provider@example.test',phone:'0000000000',profession:'nurse',specialty:'General',license_number:'TEST123',license_jurisdiction:'Synthetic',license_expiry:'2099-01-01'}))form.elements[key].value=value;
  form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,20));
  const call=calls.find(c=>c.path==='/api/provider-registration'&&c.opts.method==='POST');assert.ok(call);const data=JSON.parse(call.opts.body);assert.equal(data.profession,'nurse');assert.equal(data.hospital_slug,'existing-hospital');assert.equal(data.role,undefined);
  await w.testing.professionalsView();assert.ok(calls.find(c=>c.path==='/api/provider-applications'));assert.match(w.document.getElementById('dashboard').textContent,/Register provider/);
 }finally{dom.window.close();}
});
