import assert from "node:assert/strict";
import {test} from "node:test";
import {act,createElement,StrictMode} from "react";
import {createRoot} from "react-dom/client";
import {JSDOM} from "jsdom";
import {ZebraAgentProvider,useZebraReadable,useZebraReadableCommandRecovery,useZebraClientStatus} from "../src/index.ts";
Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});
test("pending reload exposes recovery Hook without start, mount or release; acknowledgement never restarts",async()=>{
 const dom=new JSDOM('<div id="root"></div>',{url:'https://business.example'});
 Object.assign(globalThis,{window:dom.window,document:dom.window.document,Node:dom.window.Node,HTMLElement:dom.window.HTMLElement});
 const sid='11111111-1111-4111-8111-111111111111',tid='22222222-2222-4222-8222-222222222222',bid='33333333-3333-4333-8333-333333333333',key='44444444-4444-4444-8444-444444444444',cid='55555555-5555-4555-8555-555555555555';
 dom.window.sessionStorage.setItem(`zebra:command-recovery:${sid}:${tid}:run-1`,JSON.stringify([key]));const calls:string[]=[];
 const config={mode:'bff' as const,commandRecoveryVersion:1 as const,clientStateVersion:1 as const,surfaceMetadataVersion:1 as const,baseUrl:'/api/agent/surface',clientSessionId:sid,controller:true,taskId:tid,runId:'run-1',runBindingId:bid,clientBindingDigest:'b'.repeat(64),actionContractDigests:{},initialUiRevision:0,storage:dom.window.sessionStorage,
 fetchImpl:(async(url)=>{calls.push(String(url));return Response.json({status:'accepted',commandId:cid});}) as typeof fetch};
 let recovery!:NonNullable<ReturnType<typeof useZebraReadableCommandRecovery>>;
 function Panel(){const value=useZebraReadableCommandRecovery();if(value)recovery=value;useZebraReadable('app.ui.route',{route:'/new-page'});return createElement('output',null,useZebraClientStatus());}
 const root=createRoot(dom.window.document.getElementById('root')!);
 try{
  await act(async()=>{root.render(createElement(StrictMode,null,createElement(ZebraAgentProvider,{config,frontendAppId:'web',profileRevision:1,profileDigest:'c'.repeat(64),children:createElement(Panel)})));await new Promise(r=>setTimeout(r,20));});
  assert.deepEqual(calls,[]);assert.deepEqual(recovery.pending(),[key]);assert.equal(dom.window.document.querySelector('output')?.textContent,'stopped');
  assert.deepEqual(await recovery.reconcile(key),{status:'accepted',commandId:cid});assert.deepEqual(recovery.pending(),[]);assert.equal(calls.length,1);assert.ok(calls[0]!.endsWith('/commands/receipt'));assert.equal(dom.window.document.querySelector('output')?.textContent,'stopped');
 }finally{await act(async()=>{root.unmount();await Promise.resolve();});assert.equal(calls.length,1);dom.window.close();}
});
