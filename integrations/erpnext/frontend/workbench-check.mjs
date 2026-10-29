import assert from 'node:assert/strict';
import { reduceEvent, runStatus } from './protocol.mjs';
import * as workbench from './workbench-state.mjs';
assert.equal(workbench.isActive('ready'), true, 'native ready owns an admitted request');
assert.equal(workbench.isActive('created'), true, 'native created owns an admitted request');
for (const status of ['ready','created','dispatching','accepted','queued','running']) {
  assert(workbench.isActive(status));
  assert.notEqual(runStatus(status).phase,'idle');
  assert.equal(reduceEvent({messages:[],status:'idle'},{type:'STATE_SNAPSHOT',snapshot:{session:{status}}}).status,status);
}
for (const status of ['idle','completed','cancelled','blocked','waiting_input','awaiting_approval']) assert.equal(workbench.isActive(status),false);
const { approvalDiff, UNKNOWN, confirmationReceipt, isCurrentView, rpcMethod } = workbench;
const before = {items:[{name:'a',qty:1},{name:'b',qty:2},{name:'c',qty:3}],nullable:null};
const rows = approvalDiff({items:[{name:'b',qty:4},{name:'a'}],missing:'x',nullable:null}, before);
assert(rows.some(row=>row.kind==='removed'&&row.field.includes('c')));
assert(rows.some(row=>row.kind==='reordered'));
assert(rows.some(row=>row.field==='items[b].qty'&&row.before===2&&row.after===4));
assert.equal(rows.find(row=>row.field==='missing').before, UNKNOWN);
assert(!rows.some(row=>row.field==='nullable'));
assert.equal(approvalDiff({qty:3},null)[0].before,UNKNOWN);
assert.equal(isCurrentView('a',1,'a',2),false);
assert.equal(isCurrentView('a',1,'b',1),false);
assert.equal(isCurrentView('a',1,'a',1),true);
assert.deepEqual(confirmationReceipt({name:'PP-1',doctype:'Production Plan',docstatus:0,secret:'do not show'}),{label:'已保存草稿',doctype:'Production Plan',name:'PP-1'});
assert.equal(confirmationReceipt({unexpected:'value'}).label,'服务器已返回操作结果，请核对单据');
assert.equal(rpcMethod('snapshot'),'zebra_erpnext.api.snapshot');
assert.throws(()=>rpcMethod('frappe.client.delete'));
assert.throws(()=>rpcMethod('../api'));
console.log('PASS workbench busy, child removals/reordering, unknown fields, scoped receipts and view/RPC guards');

// Execute the real Panel reader so a missing guard in either async branch fails.
const {readFileSync} = await import('node:fs');
const panel = readFileSync(new URL('./index.tsx',import.meta.url),'utf8');
const refreshBody = panel.match(/async function refreshApprovals\(name: string\) \{([\s\S]*?)\n  \}/)?.[1];
assert(refreshBody, 'the shared approval reader exists');
const refresh = new (Object.getPrototypeOf(async function(){}).constructor)('api','viewEpoch','activeConversation','setApprovals','fail','name',refreshBody);
const approvalEpoch = {current:1}, approvalSource = {current:'a'}, updates = [], failures = [];
let rejectRead;
const delayedRead = new Promise((_,reject) => {rejectRead = reject;});
const reading = refresh(()=>delayedRead,approvalEpoch,approvalSource,value=>updates.push(value),error=>failures.push(error),'a');
approvalSource.current = 'b'; approvalEpoch.current = 2; rejectRead(new Error('late A rejection'));
await assert.doesNotReject(reading, 'approval refresh is an observation and must not turn confirmed writes into failure');
assert.deepEqual(failures,[], 'late A rejection must not enter B');
assert.deepEqual(updates,[]);
await assert.doesNotReject(refresh(()=>Promise.reject(new Error('same view observation error')),approvalEpoch,approvalSource,value=>updates.push(value),error=>failures.push(error),'b'));
assert.equal(failures.length,1,'same-view observation failures remain visible');
let resolveRead;
const delayedSuccess = new Promise(resolve=>{resolveRead=resolve;});
const succeeding = refresh(()=>delayedSuccess,approvalEpoch,approvalSource,value=>updates.push(value),error=>failures.push(error),'b');
approvalEpoch.current += 1; resolveRead([{name:'stale'}]); await succeeding;
assert.deepEqual(updates,[],'same source with a newer view must reject stale success');
console.log('PASS actual approval reader contains delayed failures and rejects stale success/failure');

assert.equal(workbench.approvalFieldLabel('po_items[ROW-1].planned_qty','Production Plan'),'生产计划明细 · ROW-1 / 计划数量');
assert.equal(workbench.approvalFieldLabel('items[ROW-1].qty','Parent',name=>({fields:name==='Parent'?[{fieldname:'items',label:'原生明细',options:'Child'}]:[{fieldname:'qty',label:'原生数量'}]})),'原生明细 · ROW-1 / 原生数量');
assert.equal(workbench.approvalFieldLabel('private_field','Parent',()=>{throw Error('uncached');}),'private_field');
console.log('PASS human-readable approval fields reuse cached native metadata with bounded fallbacks');

// Run the production observe/create/select closures with deliberately stale render
// text, keeping the text input editable while their network requests are pending.
const asyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const actualBody = pattern => { const body = panel.match(pattern)?.[1]; assert(body,'production function exists'); return body; };
const actualSelect = new asyncFunction('scope','name','preserveDraft',`with(scope){${actualBody(/async function select\(name: string, preserveDraft = false\) \{([\s\S]*?)\n  \}/)}}`);
const actualObserve = new asyncFunction('scope',`with(scope){${actualBody(/async function observe\(\) \{([\s\S]*?)\n  \}/)}}`);
const actualCreate = new asyncFunction('scope','preserveDraft',`with(scope){${actualBody(/async function create\(preserveDraft = false\) \{([\s\S]*?)\n  \}/)}}`);
const actualTextSetter = new Function('textRef','setText','value',actualBody(/function changeText\(value:[^\n]+\) \{([\s\S]*?)\n  \}/));
assert.equal((panel.match(/\bsetText\(/g) || []).length,1,'all draft mutations must use the synchronous setter');
let typed = 'old', releaseBootstrap, releaseCreate;
const draftScope = {
  savingSettings:false,text:'old',textRef:{current:'old'},drafts:{current:new Map()},filesRef:{current:[]},pending:{current:null},draftEpoch:{current:1},viewEpoch:{current:1},activeConversation:{current:'a'},selected:'a',
  stopGate:{current:null},cursor:{current:''},stream:{current:null},reconnect:{current:null},runtime:{current:null},
  sessionStorage:{setItem(){}},window:{frappe:{session:{user:'fixture'}},innerWidth:1440},boot:{},conversations:[],initial:{messages:[],status:'idle'},company:'Fixture Company',
  refreshResources(){},refreshApprovals(){},isActive:workbench.isActive,isCurrentView:workbench.isCurrentView,
  setText(value){typed=value;},changeText(value){actualTextSetter(draftScope.textRef,draftScope.setText,value);},
  api:async method=>method==='snapshot'?{status:'completed'}:{},
  refreshBootstrap:()=>new Promise(resolve=>{releaseBootstrap=resolve;}),fail(error){throw error;}
};
for (const setter of ['setOpenedArtifact','setReadingFiles','setPreview','setAttachments','setDrawer','setReceipt','setConfirming','setStopping','setCatalog','setUsage','setArtifacts','setSelected','setApprovals','setError','setNotice','setState','setModel','setReasoning','setLoadingSettings','setCompany','setConversations']) draftScope[setter]=()=>{};
draftScope.select=(name,preserve=false)=>actualSelect(draftScope,name,preserve);
const observingDraft=actualObserve(draftScope);
draftScope.changeText('typed during reconnect'); releaseBootstrap({}); await observingDraft;
assert.equal(typed,'typed during reconnect','reconnect must preserve edits made after bootstrap began');
draftScope.api=method=>method==='create_conversation'?new Promise(resolve=>{releaseCreate=resolve;}):Promise.resolve(method==='snapshot'?{status:'completed'}:{});
const creatingDraft=actualCreate(draftScope,false);
draftScope.changeText('typed during create'); releaseCreate({name:'new'}); await creatingDraft;
assert.equal(draftScope.drafts.current.get('a').text,'typed during create','new session must preserve the latest old-session draft');
await draftScope.select('a');
assert.equal(typed,'typed during create','switching back restores the latest draft');
draftScope.changeText('');
assert.equal(draftScope.textRef.current,'');
draftScope.changeText(previous=>previous || 'attachment fallback');
assert.equal(draftScope.textRef.current,'attachment fallback');
assert.equal(typed,'attachment fallback');
console.log('PASS actual draft setter and delayed bootstrap/create/select closures preserve editable drafts');
