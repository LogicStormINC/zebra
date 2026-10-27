/** Paired acceptance: packaged SDK -> cookie reference BFF -> actual Go journal -> native HTTP. */
import assert from 'node:assert/strict';
import {spawn,execFileSync} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtemp,mkdir,readFile,writeFile,readdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
import {chromium,webkit} from '@playwright/test';
import {createNativeSurfaceBff} from './native-surface-bff.mjs';
const sdk=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(sdk,'../..');
const executable=process.env.OVERDOZE_BFF_ACCEPTANCE_BIN;assert.ok(executable,'explicit paired Go acceptance binary required');
const work=await mkdtemp(join(tmpdir(),'command-recovery-')),container='ca-command-recovery-'+process.pid+'-'+Date.now();
let nativeProcess,goProcess,goReplica,server;const reports=[];
const run=(cmd,args,cwd=repo)=>new Promise((ok,fail)=>{const p=spawn(cmd,args,{cwd,stdio:'inherit'});p.on('error',fail);p.on('exit',code=>code===0?ok():fail(Error(`${cmd}: ${code}`)));});
async function until(fn,label){for(let i=0;i<200;i++){try{const value=await fn();if(value)return value;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error(label);}
async function stop(p){if(p&&p.exitCode===null){p.kill();await new Promise(r=>p.once('exit',r));}}
try{
 await run('docker',['run','-d','--name',container,'-e','POSTGRES_PASSWORD=fixture','-e','POSTGRES_DB=fixture','-p','127.0.0.1::5432','postgres:17-alpine']);
 await until(()=>{execFileSync('docker',['exec',container,'pg_isready','-h','127.0.0.1','-U','postgres'],{stdio:'ignore'});return true;},'PG readiness');
 await run('docker',['exec',container,'psql','-U','postgres','-c','CREATE DATABASE business']);
 const port=execFileSync('docker',['port',container,'5432'],{encoding:'utf8'}).trim().split(':').at(-1);
 const web=join(work,'web'),packs=join(work,'packs');await mkdir(web);await mkdir(packs);const deps={vite:'6.4.3'};
 for(const pkg of ['contracts','client-core']){const before=await readdir(packs);await run('pnpm',['pack','--pack-destination',packs],join(sdk,'packages',pkg));const file=(await readdir(packs)).find(f=>!before.includes(f));deps[`@zebra-agent/${pkg}`]=`file:${join(packs,file)}`;}
 await writeFile(join(web,'package.json'),JSON.stringify({private:true,dependencies:deps,pnpm:{overrides:Object.fromEntries(Object.entries(deps).filter(([k])=>k.startsWith('@zebra-agent/')))}}));
 await run('pnpm',['install','--ignore-workspace','--no-frozen-lockfile'],web);
 await writeFile(join(web,'index.html'),'<div id="status"></div><button id="send">send</button><button id="reconcile">reconcile</button><script type="module" src="/main.ts"></script>');
 await writeFile(join(web,'main.ts'),`
import {ZebraClientRuntime,createCommandRecoveryInbox} from '@zebra-agent/client-core';
const inbox=createCommandRecoveryInbox({path:'/inbox'});window.inbox=inbox;
if(location.hash!=='#inbox'){
const boot=await(await fetch('/fixture/config')).json();
const runtime=ZebraClientRuntime.fromConfig(boot.config);window.runtime=runtime;
const status=document.querySelector('#status');
if(runtime.readableCommandRecovery.pending().length){status.textContent='pending'}else{
runtime.mountReadable('app.ui.route',{route:'/original-page',privateValue:'private-page-value'});
await runtime.mount({frontendAppId:boot.profile.frontend_app_id,profileRevision:boot.profile.revision,profileDigest:boot.profile.profile_digest,mountedActions:[],mountedReadables:['app.ui.route']});status.textContent='ready';}
document.querySelector('#send').onclick=async()=>{try{await runtime.submitReadableCommand({action:'run',expectedRevision:boot.revision,idempotencyKey:boot.key,input:{messages:[]}});status.textContent='accepted'}catch{status.textContent='unknown'}};
document.querySelector('#reconcile').onclick=async()=>{try{const result=await runtime.readableCommandRecovery.reconcile(boot.key);status.textContent=result.status}catch{status.textContent='unavailable'}};
}else{document.querySelector('#status').textContent='inbox-ready'}
`);
 await writeFile(join(web,'vite.config.mjs'),'export default {build:{target:"es2022"}}');await run('pnpm',['exec','vite','build'],web);
 for(const [label,engine]of [['chromium',chromium],['webkit',webkit]]){
  const folder=join(work,label);await mkdir(folder);await writeFile(join(folder,'native-input.json'),JSON.stringify({dsn:`postgresql://postgres:fixture@127.0.0.1:${port}/fixture`,readable:true}),{mode:0o600});
  nativeProcess=spawn(join(repo,'.venv/bin/python'),['-m','tests.acceptance.native_surface_server',folder],{cwd:repo,env:Object.fromEntries(Object.entries(process.env).filter(([k])=>!/^(ZEBRA_|OVERDOZE_|PG|AWS_|OPENAI_|DEEPSEEK_|PYTHONPATH$|HTTP_PROXY$|HTTPS_PROXY$|ALL_PROXY$)/i.test(k))),stdio:['ignore','ignore','inherit']});
  const native=await until(async()=>JSON.parse(await readFile(join(folder,'native-ready.json'),'utf8')),'native startup');native.commandRecoveryVersion=1;
  const mapping=join(folder,'mapping.json'),secret=randomUUID(),key=randomUUID();let goUrl='',replicaUrl='',posts=0,gets=0,loginCookie='';
  const bff=await createNativeSurfaceBff(native,mapping,async(action,body,idempotencyKey)=>{
   if(action==='commands')posts++;else gets++;
   const destinations=action==='commands'?[goUrl]:[goUrl];
   const results=await Promise.all(destinations.map(async url=>{
    const response=await fetch(url+'/commands'+(action==='commandReceipt'?'/receipt':''),{method:action==='commandReceipt'?'GET':'POST',headers:{'Content-Type':'application/json',Origin:url,'X-Fixture-Secret':secret,'Idempotency-Key':idempotencyKey},...(action==='commands'?{body:JSON.stringify(body)}:{})});
    return {code:response.status,body:await response.json()};
   }));
   assert.ok(results.every(result=>result.code===200));
   // Lose the initial browser acknowledgement even if the other replica already observed admission.
   return action==='commands'?{code:200,body:{status:'unknown'}}:results[0];
  });
  const ready=join(folder,'go-ready.json'),input=join(folder,'go-input.json');await writeFile(input,JSON.stringify({DSN:`postgresql://postgres:fixture@127.0.0.1:${port}/business?sslmode=disable`,NativeFile:join(folder,'native-ready.json'),MappingFile:mapping,Secret:secret,Tenant:label,ReadyFile:ready}),{mode:0o600});
  async function startGo(){await rm(ready,{force:true});goProcess=spawn(executable,[input],{stdio:['ignore','ignore','inherit']});goUrl=await until(async()=>JSON.parse(await readFile(ready,'utf8')).url,'Go BFF startup');}
  await startGo();
  const replicaInput=join(folder,'go-replica-input.json'),replicaReady=join(folder,'go-replica-ready.json');
  await writeFile(replicaInput,JSON.stringify({...JSON.parse(await readFile(input,'utf8')),ReadyFile:replicaReady}),{mode:0o600});
  goReplica=spawn(executable,[replicaInput],{stdio:['ignore','ignore','inherit']});replicaUrl=await until(async()=>JSON.parse(await readFile(replicaReady,'utf8')).url,'second Go process startup');
  server=createServer(async(req,res)=>{try{
   if(req.url==='/fixture/config'){
    const current=JSON.parse(await readFile(mapping,'utf8')).metadata;
    res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');res.end(JSON.stringify({config:{...bff.config,initialUiRevision:current.ui_revision,clientBindingDigest:current.binding_digest,runBindingId:current.binding_id,actionContractDigests:current.action_contract_digests},profile:native.profile,revision:native.commandRevision,key}));return;
   }
   if(req.url.startsWith('/inbox')){
    if(!bff.state.authorized||!loginCookie||req.headers.cookie!==loginCookie){res.writeHead(401);res.end('{}');return;}
    let body='';for await(const chunk of req)body+=chunk;
    const upstream=replicaUrl;const response=await fetch(upstream+req.url,{method:req.method,headers:{Origin:upstream,'Content-Type':'application/json','X-Fixture-Secret':secret,...(req.headers['idempotency-key']?{'Idempotency-Key':req.headers['idempotency-key']}:{})},...(req.method==='POST'?{body}:{})});
    res.writeHead(response.status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(await response.text());return;
   }
   if(await bff.handle(req,res)){if(req.url==='/fixture/login')loginCookie=String(res.getHeader('set-cookie')).split(';')[0];return;}
   if(req.url!=='/'&&!/^\/assets\/[A-Za-z0-9_-]+\.js$/.test(req.url)){res.writeHead(404);res.end();return;}
   const file=join(web,'dist',req.url==='/'?'index.html':req.url);res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':'text/html');res.end(await readFile(file));
  }catch{res.writeHead(503);res.end('{}');}});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));bff.state.origin=`http://127.0.0.1:${server.address().port}`;
  const browser=await engine.launch(),page=await browser.newPage();const wire=[];page.on('response',async r=>{if(r.url().includes('/api/agent/'))try{wire.push(await r.text());}catch{}});
  try{
   await page.goto(bff.state.origin+'/fixture/login');await page.goto(bff.state.origin);await page.locator('#status').filter({hasText:'ready'}).waitFor();
   await page.locator('#send').click();await page.locator('#status').filter({hasText:'unknown'}).waitFor();assert.equal(posts,1);
   const before=await(await fetch(native.nativeUrl+'/fixture/readable-report',{headers:{'X-Fixture-Key':native.fixtureKey}})).json();assert.equal(before.commands,1);assert.equal(before.lastState['app.ui.route'].route,'/original-page');
   await fetch(replicaUrl+'/fixture/unobservable',{method:'POST',headers:{'X-Fixture-Secret':secret}});
   const other=await browser.newContext(),device=await other.newPage();
   await device.goto(bff.state.origin+'/fixture/login');await device.goto(bff.state.origin+'/#inbox');await device.locator('#status').filter({hasText:'inbox-ready'}).waitFor();
   assert.equal(await device.evaluate(()=>sessionStorage.length),0);
   const discovered=await device.evaluate(()=>window.inbox.discover());assert.equal(discovered.items.length,1);assert.equal(discovered.items[0].key,key);
   const unavailable=await device.evaluate(async key=>{try{await window.inbox.reconcile(key);return false}catch{return true}},key);assert.equal(unavailable,true);
   const handled=await device.evaluate(key=>window.inbox.handle(key,{revision:0,action:'escalate',reason:'unobservable'}),key);assert.equal(handled.revision,1);
   const blocked=await device.evaluate(async()=>{try{await window.inbox.assertClear();return false}catch(e){return e.code==='command_recovery_pending'}});assert.equal(blocked,true);
   const stale=await device.evaluate(async key=>{try{await window.inbox.handle(key,{revision:0,action:'escalate',reason:'unobservable'});return false}catch{return true}},key);assert.equal(stale,true);
   await stop(goReplica);goReplica=undefined;await rm(replicaReady,{force:true});
   goReplica=spawn(executable,[replicaInput],{stdio:['ignore','ignore','inherit']});replicaUrl=await until(async()=>JSON.parse(await readFile(replicaReady,'utf8')).url,'restarted inbox replica');
   await device.reload();await device.locator('#status').filter({hasText:'inbox-ready'}).waitFor();
   const persisted=await device.evaluate(()=>window.inbox.discover());assert.equal(persisted.items[0].handling.revision,1);assert.equal(persisted.items[0].status,'unknown');assert.equal(posts,1);
   const accepted=await device.evaluate(key=>window.inbox.reconcile(key),key);assert.equal(accepted.status,'accepted');
   await device.evaluate(()=>window.inbox.assertClear());assert.equal(posts,1);await other.close();
   const after=await(await fetch(native.nativeUrl+'/fixture/readable-report',{headers:{'X-Fixture-Key':native.fixtureKey}})).json();assert.deepEqual(after.states,before.states);assert.equal(after.commands,1);
   await page.reload();await page.locator('#status').filter({hasText:'pending'}).waitFor();await page.locator('#reconcile').click();await page.locator('#status').filter({hasText:'accepted'}).waitFor();assert.equal(posts,1);
   const visible=JSON.stringify(wire)+await page.evaluate(()=>JSON.stringify(sessionStorage));for(const value of [native.credential,secret,'private-page-value'])assert.ok(!visible.includes(value));
   bff.state.authorized=false;const denied=await page.evaluate(async ({config,key})=>(await fetch(config.baseUrl+`/agui/threads/${config.taskId}/runs/run-1/commands/receipt`,{headers:{'Idempotency-Key':key}})).status,{config:bff.config,key});assert.equal(denied,401);
   reports.push({browser:label,commands:1,crossDeviceEmptyStorage:true,twoGoProcesses:true,unobservableRefused:true,manualCAS:true,unknownStillBlocking:true,restartAuditPreserved:true,lateOriginalReceipt:true,noResend:true,originalStatePreserved:true,privateStorageSafe:true});
  }finally{await browser.close();await new Promise(r=>server.close(r));server=undefined;await stop(goProcess);goProcess=undefined;await stop(goReplica);goReplica=undefined;await stop(nativeProcess);nativeProcess=undefined;}
 }
 console.log(JSON.stringify({contract:'request-discovery/1',boundary:'actual Go business journal in separate owned PostgreSQL DB; native HTTP/local authority/SQLite commands and Worker Context; fixture Cookie and private bridge, not production IdP/cloud/HA',reports},null,2));
}finally{await stop(goProcess);await stop(goReplica);await stop(nativeProcess);server?.close();execFileSync('docker',['rm','-f','-v',container],{stdio:'ignore'});await rm(work,{recursive:true,force:true});}
