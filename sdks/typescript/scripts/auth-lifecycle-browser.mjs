/** Packaged SDK -> business-verified callback + Go encrypted sessions -> actual native mount HTTP.
 * Business IdP verification/cookie and native local-profile credentials are explicit fixtures.
 */
import assert from 'node:assert/strict';
import {spawn,execFileSync} from 'node:child_process';
import {createServer,request} from 'node:http';
import {mkdtemp,mkdir,readdir,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium,webkit} from '@playwright/test';
import {createNativeSurfaceBff} from './native-surface-bff.mjs';
const sdk=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(sdk,'../..');
const binary=process.env.OVERDOZE_LOGIN_FIXTURE_BIN;assert.ok(binary,'explicit Go login fixture binary required');
const work=await mkdtemp(join(tmpdir(),'login-lifecycle-')),container='native-login-'+process.pid+'-'+Date.now(),reports=[];
let server,nativeProcess,goProcess,goExit,goURL,bff,native,mapping,cookie,origin;
const run=(cmd,args,cwd=repo)=>new Promise((ok,fail)=>{const p=spawn(cmd,args,{cwd,stdio:'inherit'});p.on('error',fail);p.on('exit',code=>code===0?ok():fail(Error(`${cmd}: ${code}`)));});
async function until(fn,label){for(let n=0;n<300;n++){try{const v=await fn();if(v)return v;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error(label);}
async function stopNative(){if(nativeProcess&&nativeProcess.exitCode===null){nativeProcess.kill();await new Promise(r=>nativeProcess.once('exit',r));}nativeProcess=null;}
async function stopGo(){if(goProcess&&goProcess.exitCode===null){if(goURL)await fetch(goURL+'/business/stop',{method:'POST',headers:{Origin:origin,Cookie:cookie}}).catch(()=>{});await Promise.race([goExit,new Promise(r=>setTimeout(r,10000))]);if(goProcess.exitCode===null)goProcess.kill();}goProcess=null;goURL='';}
try{
 const web=join(work,'web'),packs=join(work,'packs');await mkdir(web);await mkdir(packs);const deps={vite:'6.4.3'};
 for(const pkg of ['contracts','client-core']){const before=await readdir(packs);await run('pnpm',['pack','--pack-destination',packs],join(sdk,'packages',pkg));const file=(await readdir(packs)).find(x=>!before.includes(x));assert.ok(file);deps[`@zebra-agent/${pkg}`]=`file:${join(packs,file)}`;}
 await writeFile(join(web,'package.json'),JSON.stringify({private:true,dependencies:deps,pnpm:{overrides:Object.fromEntries(Object.entries(deps).filter(([k])=>k.startsWith('@zebra-agent/')))}}));await run('pnpm',['install','--ignore-workspace','--no-frozen-lockfile'],web);
 await writeFile(join(web,'index.html'),'<div id="ready">loading</div><script type="module" src="/main.ts"></script>');
 await writeFile(join(web,'main.ts'),`
import {createBFFAuth,createAuthenticatedRuntime,ZebraClientRuntime} from '@zebra-agent/client-core';
window.auth=createBFFAuth({path:'/auth',storage:sessionStorage});window.instances=[];
window.life=createAuthenticatedRuntime({auth:window.auth,
 bootstrap:async(signal)=>{const r=await fetch('/bootstrap',{signal,credentials:'same-origin',cache:'no-store',redirect:'error'});if(!r.ok)throw Error('bootstrap rejected');return r.json();},
 create:boot=>{const r=ZebraClientRuntime.fromConfig(boot.config);window.instances.push(r);return r;},
 mount:async(runtime,boot)=>{await runtime.mount({frontendAppId:boot.profile.frontend_app_id,profileRevision:boot.profile.revision,profileDigest:boot.profile.profile_digest,mountedActions:[],mountedReadables:[]});}
});document.querySelector('#ready').textContent='ready';`);
 await writeFile(join(web,'vite.config.mjs'),'export default {build:{target:"es2022"}}');await run('pnpm',['exec','vite','build'],web);
 await run('docker',['run','-d','--name',container,'-e','POSTGRES_PASSWORD=fixture','-e','POSTGRES_DB=native','-p','127.0.0.1::5432','postgres:17-alpine']);
 await until(()=>{execFileSync('docker',['exec',container,'pg_isready','-h','127.0.0.1','-U','postgres'],{stdio:'ignore'});return true;},'native PG readiness');
 const port=execFileSync('docker',['port',container,'5432'],{encoding:'utf8'}).trim().split(':').at(-1);
 async function allowed(req,path='/business/admission'){
  if(!goURL)return false;const response=await fetch(goURL+path,{headers:{Cookie:req.headers.cookie??'',Host:new URL(origin).host},signal:AbortSignal.timeout(5000)});return response.status===204;
 }
 server=createServer(async(req,res)=>{try{
  if(req.url.startsWith('/auth')||req.url.startsWith('/business/')){
   if(!goURL){res.writeHead(503).end();return;}
   const upstream=request(new URL(req.url,goURL),{method:req.method,headers:req.headers},response=>{res.writeHead(response.statusCode,response.headers);response.pipe(res);});upstream.on('error',()=>{if(!res.headersSent)res.writeHead(503);res.end();});req.pipe(upstream);return;
  }
  if(req.url==='/bootstrap'){
   if(!await allowed(req)){res.writeHead(401).end('{}');return;}
   const metadata=JSON.parse(await readFile(mapping,'utf8')).metadata;
   const config={...bff.config,initialUiRevision:metadata.ui_revision,clientBindingDigest:metadata.binding_digest,runBindingId:metadata.binding_id,actionContractDigests:metadata.action_contract_digests};
   res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'}).end(JSON.stringify({config,profile:native.profile}));return;
  }
  if(req.url.startsWith('/api/agent/')){
   // Cleanup release requires CURRENT business owner, while every admission/action needs Access.
   if(!await allowed(req,req.url.endsWith('/release')?'/business/current':'/business/admission')){res.writeHead(401).end('{}');return;}
  }
  if(bff&&await bff.handle(req,res))return;
  const pathname=new URL(req.url,origin).pathname;if(pathname.includes('..')||pathname.includes('%')||pathname.includes('\\')){res.writeHead(404).end();return;}
  const file=join(web,'dist',pathname==='/'?'index.html':pathname);const data=await readFile(file);res.setHeader('content-type',file.endsWith('.js')?'text/javascript':'text/html');res.end(data);
 }catch{if(!res.headersSent)res.writeHead(503);res.end('{}');}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));origin=`http://127.0.0.1:${server.address().port}`;
 for(const [name,engine]of [['chromium',chromium],['webkit',webkit]]){
  const folder=join(work,name);await mkdir(folder);await writeFile(join(folder,'native-input.json'),JSON.stringify({dsn:`postgresql://postgres:fixture@127.0.0.1:${port}/native`}),{mode:0o600});
  nativeProcess=spawn(join(repo,'.venv/bin/python'),['-m','tests.acceptance.native_surface_server',folder],{cwd:repo,env:Object.fromEntries(Object.entries(process.env).filter(([k])=>!/^(ZEBRA_|OVERDOZE_|PG|AWS_|OPENAI_|DEEPSEEK_|PYTHONPATH$|HTTP_PROXY$|HTTPS_PROXY$|ALL_PROXY$)/i.test(k))),stdio:['ignore','ignore','inherit']});
  native=await until(async()=>JSON.parse(await readFile(join(folder,'native-ready.json'),'utf8')),'native HTTP startup');mapping=join(folder,'private-mapping.json');bff=await createNativeSurfaceBff(native,mapping);bff.state.origin=origin;
  const login=await fetch(origin+'/fixture/login');cookie=login.headers.get('set-cookie').split(';')[0];assert.ok(cookie.startsWith('business='));
  const ready=join(folder,'go-ready'),config=join(folder,'go-config.json');await writeFile(config,JSON.stringify({Origin:origin,Cookie:cookie,Ready:ready}),{mode:0o600});
  goProcess=spawn(binary,['-test.run','^TestBusinessLoginLifecycleBrowserFixture$','-test.v'],{env:{...process.env,OVERDOZE_LOGIN_BROWSER_FILE:config},stdio:['ignore','pipe','pipe']});let output='';goProcess.stdout.on('data',d=>{output+=d;});goProcess.stderr.on('data',d=>{output+=d;});goExit=new Promise(r=>goProcess.once('exit',r));
  goURL=await until(async()=>{if(goProcess.exitCode!==null)throw Error(output);return (await readFile(ready,'utf8')).trim();},'business callback fixture');
  const browser=await engine.launch({headless:true});
  try{
   const context=await browser.newContext();const [cookieName,cookieValue]=cookie.split('=');await context.addCookies([{name:cookieName,value:cookieValue,url:origin,httpOnly:true,sameSite:'Strict'}]);
   const page=await context.newPage();await page.goto(origin);await page.waitForFunction(()=>window.life);
   const control=async(action)=>{const r=await context.request.post(origin+'/business/control',{headers:{Origin:origin,'X-Fixture-Action':action}});assert.equal(r.status(),action==='reauth'?200:204);};
   const stats=async()=>await(await context.request.get(origin+'/business/stats')).json();
   assert.equal(await page.evaluate(async()=>{try{await window.life.start();return false;}catch{return true;}}),true);assert.equal(bff.state.mounts.length,0);
   // Actual callback installs successfully but loses its browser acknowledgement.
   const lost=await context.request.post(origin+'/business/callback',{headers:{Origin:origin,'X-Business-Verified':'1','X-Fixture-Response-Loss':'1'}});assert.equal(lost.status(),503);assert.equal((await stats()).issues,1);
   const receipt=await(await context.request.get(origin+'/business/receipt')).json();assert.equal(receipt.outcome,'completed');
   assert.equal((await context.request.post(origin+'/business/callback',{headers:{Origin:origin,'X-Business-Verified':'1'}})).status(),200);assert.equal((await stats()).issues,1);
   await page.evaluate(async()=>{await window.life.start();});assert.equal(bff.state.mounts.length,1);const firstFence=bff.state.fences.at(-1);
   const state=await page.evaluate(()=>window.auth.state());await control('loss');
   assert.equal(await page.evaluate(async revision=>{try{await window.life.refresh(revision);return false;}catch{return true;}},state.revision),true);
   assert.equal(await page.evaluate(()=>window.instances.every(r=>r.isStopped)),true);await until(()=>bff.state.releases>=1,'old native Controller release');
   await control('restore');const marker=await page.evaluate(()=>window.auth.pending());assert.ok(marker);const before=(await stats()).refreshes;
   await page.reload();await page.waitForFunction(()=>window.life);assert.equal(await page.evaluate(async()=>{try{await window.life.start();return false;}catch{return true;}}),true);
   const unknown=await page.evaluate(id=>window.life.inspect(id),marker.operation);assert.equal(unknown.status,'unknown');assert.equal((await stats()).refreshes,before);assert.equal(bff.state.mounts.length,1);
   const closed=await page.evaluate(rev=>window.life.retire(rev),unknown.revision);assert.equal(closed.status,'closed');await control('reauth');assert.equal((await stats()).issues,2);
   await page.evaluate(async()=>{await window.life.start();});assert.equal(bff.state.mounts.length,2);assert.notEqual(bff.state.fences.at(-1),firstFence);
   await control('deny');await page.evaluate(async()=>{try{await window.life.sync();}catch{}});assert.equal(await page.evaluate(()=>window.life.runtime===null&&window.instances.every(r=>r.isStopped)),true);
   const publicState=await page.evaluate(()=>JSON.stringify({storage:{...sessionStorage},cookies:document.cookie}));assert.ok(!/ag_access_|ag_refresh_|agid_|od_server_|business=/.test(publicState));
   reports.push({browser:name,verifiedBusinessCallbackFixture:true,actualPlatformHTTP:true,separateBusinessPG:true,lostCallbackAckReadOnlyRecovery:true,duplicateCallbackIssuePosts:1,actualNativeHTTPMounts:2,newControllerFence:true,runtimeStoppedBeforeUnknownRefresh:true,reloadNoRemountOrRetry:true,explicitReauthAndRestart:true,currentBusinessDenialStopsRuntime:true,noBrowserCredentials:true,nativeLocalCompatibilityFixture:true});await context.close();
  }finally{await browser.close();}
  await stopGo();assert.equal(await goExit,0,output);await stopNative();bff=null;
 }
 const report=JSON.stringify({version:'1',reports},null,2);if(process.env.OVERDOZE_LIFECYCLE_REPORT)await writeFile(process.env.OVERDOZE_LIFECYCLE_REPORT,report+'\n');console.log(report);
}finally{
 await stopGo();await stopNative();if(server)await new Promise(r=>server.close(r));try{execFileSync('docker',['rm','-f',container],{stdio:'ignore'});}catch{}await rm(work,{recursive:true,force:true});
}
