/** Opt-in paired acceptance: packaged SDK + actual Go facade/platform HTTP + separate business PG.
 * The cookie and business reauthentication callbacks are fixtures, not a production IdP.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer,request} from 'node:http';
import {mkdtemp,mkdir,readdir,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {chromium,webkit} from '@playwright/test';
const sdk=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const binary=process.env.OVERDOZE_AUTH_FIXTURE_BIN;
assert.ok(binary,'explicit Go auth fixture test binary required');
const work=await mkdtemp(join(tmpdir(),'bff-auth-')),reports=[];
let server,child,backend,childExit;
const run=(cmd,args,cwd)=>new Promise((ok,fail)=>{const p=spawn(cmd,args,{cwd,stdio:'inherit'});p.on('error',fail);p.on('exit',code=>code===0?ok():fail(Error(`${cmd}: ${code}`)));});
async function until(fn,label){for(let n=0;n<300;n++){try{const v=await fn();if(v)return v;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error(label);}
try{
 const web=join(work,'web'),packs=join(work,'packs');await mkdir(web);await mkdir(packs);const deps={vite:'6.4.3'};
 for(const pkg of ['contracts','client-core']){
  const before=await readdir(packs);await run('pnpm',['pack','--pack-destination',packs],join(sdk,'packages',pkg));
  const file=(await readdir(packs)).find(x=>!before.includes(x));assert.ok(file);deps[`@zebra-agent/${pkg}`]=`file:${join(packs,file)}`;
 }
 await writeFile(join(web,'package.json'),JSON.stringify({private:true,dependencies:deps,pnpm:{overrides:Object.fromEntries(Object.entries(deps).filter(([k])=>k.startsWith('@zebra-agent/')))}}));
 await run('pnpm',['install','--ignore-workspace','--no-frozen-lockfile'],web);
 await writeFile(join(web,'index.html'),'<div id="ready">loading</div><script type="module" src="/main.ts"></script>');
 await writeFile(join(web,'main.ts'),`import {createBFFAuth} from '@zebra-agent/client-core';
window.auth=createBFFAuth({path:'/auth',storage:sessionStorage});document.querySelector('#ready').textContent='ready';`);
 await writeFile(join(web,'vite.config.mjs'),'export default {build:{target:"es2022"}}');await run('pnpm',['exec','vite','build'],web);
 server=createServer(async(req,res)=>{
  if(req.url.startsWith('/auth')||req.url.startsWith('/fixture/')){
   if(!backend){res.writeHead(503).end();return;}
   const target=new URL(req.url,backend);
   const upstream=request(target,{method:req.method,headers:req.headers},response=>{res.writeHead(response.statusCode,response.headers);response.pipe(res);});
   upstream.on('error',()=>{if(!res.headersSent)res.writeHead(503);res.end();});req.pipe(upstream);return;
  }
  const pathname=new URL(req.url,'http://fixture').pathname;
  if(pathname.includes('..')||pathname.includes('%')||pathname.includes('\\')){res.writeHead(404).end();return;}
  try{const file=join(web,'dist',pathname==='/'?'index.html':pathname);const data=await readFile(file);res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(data);}catch{res.writeHead(404).end();}
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
 const ready=join(work,'ready'),config=join(work,'config.json');await writeFile(config,JSON.stringify({Origin:origin,Ready:ready}),{mode:0o600});
 child=spawn(binary,['-test.run','^TestBFFAuthBrowserFixture$','-test.v'],{env:{...process.env,OVERDOZE_AUTH_FIXTURE_FILE:config},stdio:['ignore','pipe','pipe']});
 let output='';child.stdout.on('data',d=>{output+=d;});child.stderr.on('data',d=>{output+=d;});childExit=new Promise(r=>child.once('exit',code=>r(code)));
 backend=await until(async()=>{if(child.exitCode!==null)throw Error(output);return (await readFile(ready,'utf8')).trim();},'Go auth fixture readiness');
 for(const [name,engine] of [['chromium',chromium],['webkit',webkit]]){
  const browser=await engine.launch({headless:true});
  try{
   const context=await browser.newContext();await context.addCookies([{name:'business',value:'owner',url:origin,httpOnly:true,sameSite:'Strict'}]);
   const page=await context.newPage();await page.goto(origin);await page.waitForFunction(()=>window.auth);
   const control=async(action)=>{const response=await context.request.post(`${origin}/fixture/control`,{headers:{Origin:origin,'X-Fixture-Action':action}});assert.equal(response.status(),204);};
   const stats=async()=>(await (await context.request.get(`${origin}/fixture/stats`)).json()).refreshes;
   if(name==='webkit')await control('reauth');
   let state=await page.evaluate(()=>window.auth.assertActive());assert.equal(state.status,'active');
   const before=await stats();state=await page.evaluate(rev=>window.auth.refresh(rev),state.revision);assert.equal(state.status,'active');assert.equal(await stats(),before+1);
   // Actually consumed platform refresh response is lost before the BFF can persist the new pair.
   await control('loss');assert.equal(await page.evaluate(async rev=>{try{await window.auth.refresh(rev);return false;}catch{return true;}},state.revision),true);
   const marker=await page.evaluate(()=>window.auth.pending());assert.equal(marker.kind,'refresh');const afterLoss=await stats();assert.equal(afterLoss,before+2);
   await control('restore');await page.reload();await page.waitForFunction(()=>window.auth);
   assert.equal((await page.evaluate(()=>window.auth.pending())).operation,marker.operation);
   state=await page.evaluate(id=>window.auth.inspect(id),marker.operation);assert.equal(state.status,'unknown');assert.equal(state.receipt.outcome,'unknown');
   assert.equal(await page.evaluate(async()=>{try{await window.auth.assertActive();return false;}catch{return true;}}),true);
   assert.equal(await page.evaluate(async rev=>{try{await window.auth.refresh(rev);return false;}catch{return true;}},state.revision),true);
   // A second device has no local marker, but server unknown still blocks admission and SDK bootstrap.
   const other=await context.newPage();await other.goto(origin);await other.waitForFunction(()=>window.auth);
   assert.equal(await other.evaluate(async()=>{try{await window.auth.assertActive();return false;}catch{return true;}}),true);
   assert.equal((await context.request.get(`${origin}/fixture/admission`)).status(),401);assert.equal(await stats(),afterLoss);
   const closed=await page.evaluate(rev=>window.auth.retire(rev),state.revision);assert.equal(closed.status,'closed');assert.equal(await page.evaluate(()=>window.auth.pending()),null);
   const original=await page.evaluate(id=>window.auth.inspect(id),marker.operation);assert.equal(original.receipt.outcome,'unknown');assert.equal(original.status,'closed');
   await control('reauth');state=await page.evaluate(()=>window.auth.assertActive());assert.equal(state.status,'active');assert.equal(await stats(),afterLoss);
   assert.equal((await context.request.get(`${origin}/fixture/admission`)).status(),204);
   await control('expire');state=await page.evaluate(()=>window.auth.state());assert.equal(state.status,'refresh_required');
   assert.equal(await page.evaluate(async()=>{try{await window.auth.assertActive();return false;}catch{return true;}}),true);
   state=await page.evaluate(rev=>window.auth.refresh(rev),state.revision);assert.equal(state.status,'active');assert.equal(await stats(),afterLoss+1);
   const csrf=await context.request.post(`${origin}/auth/refresh`,{headers:{Origin:'https://evil.example','X-Overdoze-Auth':'1','Idempotency-Key':'11111111-1111-4111-8111-111111111111'},data:{revision:state.revision}});assert.equal(csrf.status(),403);
   await control('deny');assert.equal(await page.evaluate(async()=>{try{await window.auth.assertActive();return false;}catch{return true;}}),true);await control('allow');
   const stored=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage},cookie:document.cookie}));
   assert.ok(!/ag_access_|ag_refresh_|agid_|od_server_|business=/.test(stored));
   state=await page.evaluate(()=>window.auth.state());await page.evaluate(rev=>window.auth.retire(rev),state.revision);
   reports.push({browser:name,actualPlatformHTTP:true,separateBusinessPG:true,refreshPosts:(await stats())-before,lossFlowRefreshPosts:afterLoss-before,expiredAccessCASAndExplicitRefresh:true,lostResponseReload:true,crossDeviceUnknown:true,explicitRetirement:true,freshBusinessReauthFixture:true,noCredentialExposure:true,noAutomaticRetry:true});
   await context.close();
  }finally{await browser.close();}
 }
 await fetch(backend+'/fixture/stop',{method:'POST'});assert.equal(await childExit,0,output);
 const report=JSON.stringify({version:'1',reports},null,2);if(process.env.OVERDOZE_AUTH_REPORT)await writeFile(process.env.OVERDOZE_AUTH_REPORT,report+'\n');console.log(report);
}finally{
 if(child&&child.exitCode===null){if(backend)await fetch(backend+'/fixture/stop',{method:'POST'}).catch(()=>{});await Promise.race([childExit,new Promise(r=>setTimeout(r,10000))]);if(child.exitCode===null)child.kill();}
 if(server)await new Promise(r=>server.close(r));await rm(work,{recursive:true,force:true});
}
