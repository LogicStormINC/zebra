import assert from "node:assert/strict";

export function readableFixtureSource(config, profile, revision) { return `
import {StrictMode,useState} from 'react'; import {createRoot} from 'react-dom/client'; import {z} from 'zod';
import {ZebraAgentProvider,useZebraAction,useZebraReadable,useZebraReadableCommand,useZebraClientStatus} from '@zebra-agent/react';
const config=${JSON.stringify(config)};
function Readable({route}){useZebraReadable('app.ui.route',{route,negative:-0,large:1e100,authToken:'readable-fixture-secret'});return null}
function Panel(){const [route,setRoute]=useState('/items');const [opened,setOpened]=useState('');const [count,setCount]=useState(0);const [show,setShow]=useState(true);const [submitted,setSubmitted]=useState(0);const [revision,setRevision]=useState(${revision});const [error,setError]=useState('');const submit=useZebraReadableCommand();
useZebraAction('app.ui.item.open',{parameters:z.object({itemId:z.string()}),result:z.object({opened:z.boolean()}),handler:({itemId})=>{setOpened(itemId);setCount(n=>n+1);return {opened:true}}});
async function send(){try{await submit({action:'run',expectedRevision:revision,idempotencyKey:'browser-readable-'+submitted,input:{messages:[]}});setSubmitted(n=>n+1);setRevision(n=>n+1)}catch{setError('rejected')}}
return <>{show&&<Readable route={route}/>}<output id="status">{useZebraClientStatus()}</output><output id="opened">{opened}</output><output id="count">{count}</output><output id="submitted">{submitted}</output><output id="error">{error}</output><button id="change" onClick={()=>setRoute('/other')}>Change route</button><button id="latest" onClick={()=>setRoute('/latest')}>Latest</button><button id="clear-readable" onClick={()=>setShow(false)}>Clear</button><button id="submit-readable" onClick={send}>Submit</button></>}
createRoot(document.getElementById('root')).render(<StrictMode><ZebraAgentProvider config={config} frontendAppId=${JSON.stringify(profile.frontend_app_id)} profileRevision={${profile.revision}} profileDigest=${JSON.stringify(profile.profile_digest)}><Panel/></ZebraAgentProvider></StrictMode>);
`; }

export async function exerciseReadables(page, native, bff) {
 const report = async () => { const response=await fetch(native.nativeUrl+'/fixture/readable-report',{headers:{'X-Fixture-Key':native.fixtureKey}});assert.equal(response.status,200);return response.json(); };
 const submit=async count=>{await page.locator('#submit-readable').click();await page.locator('#submitted').filter({hasText:String(count)}).waitFor();assert.equal(await page.locator('#error').textContent(),'');};
 await submit(1); const first=await report();assert.equal(first.commands,1);assert.equal(first.lastState['app.ui.route'].route,'/other');assert.ok(first.prompt.includes('/other'));assert.ok(!first.prompt.includes('readable-fixture-secret'));assert.equal(first.lastState['app.ui.route'].authToken,'__redacted__');
 const original=bff.state.commands[0];
 const replay=await page.request.post(bff.state.origin+bff.config.baseUrl+`/agui/threads/${native.task}/runs/run-1/commands`,{headers:{Origin:bff.state.origin,'Idempotency-Key':original.key},data:original.body});assert.equal(replay.status(),200);assert.equal((await report()).commands,1);
 const before=bff.state.calls;
 for(const body of [{...original.body,threadId:'foreign'},{...original.body,surface:{...original.body.surface,uiRevision:0}},{...original.body,input:{...original.body.input,forwardedProps:{sessionCredential:'forbidden'}}}]){
  const denied=await page.request.post(bff.state.origin+bff.config.baseUrl+`/agui/threads/${native.task}/runs/run-1/commands`,{headers:{Origin:bff.state.origin,'Idempotency-Key':'denied'},data:body});assert.equal(denied.status(),409);
 }
 assert.equal(bff.state.calls,before);
 const stale=await page.request.post(bff.state.origin+bff.config.baseUrl+`/agui/threads/${native.task}/runs/run-1/commands`,{headers:{Origin:bff.state.origin,'Idempotency-Key':'stale-cas'},data:original.body});assert.equal(stale.status(),409);assert.equal((await report()).commands,1);
 const prior=bff.state.mounts.at(-1).ui_revision;await page.locator('#latest').click();
 await page.waitForFunction(()=>document.querySelector('#status')?.textContent==='ready');
 for(let i=0;bff.state.mounts.at(-1).ui_revision===prior&&i<100;i++) await new Promise(r=>setTimeout(r,20));
 assert.ok(bff.state.mounts.at(-1).ui_revision>prior);await submit(2);const second=await report();assert.equal(second.commands,2);assert.equal(second.lastState['app.ui.route'].route,'/latest');assert.equal(second.states[0]['app.ui.route'].route,'/other');
 const beforeClear=bff.state.mounts.at(-1).ui_revision;await page.locator('#clear-readable').click();
 for(let i=0;bff.state.mounts.at(-1).ui_revision===beforeClear&&i<100;i++) await new Promise(r=>setTimeout(r,20));
 assert.ok(bff.state.mounts.at(-1).ui_revision>beforeClear);await submit(3);const clear=await report();assert.equal(clear.commands,3);assert.deepEqual(clear.lastState,{});assert.ok(!clear.prompt.includes('/latest'));assert.ok(!JSON.stringify(clear).includes('readable-fixture-secret'));
 const storage=await page.evaluate(()=>JSON.stringify(sessionStorage));assert.ok(!storage.includes('readable-fixture-secret'));assert.ok(!storage.includes('/latest'));
 return { readableCommands:3, commandReplay:true, staleCasRejected:true, callerAuthorityRejected:true, immutableHistoricalState:true, reopenedWorkerContext:true, emptyStateClears:true };
}
