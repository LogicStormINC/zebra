import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { ZebraAgentProvider, useZebraReadable, useZebraReadableCommand } from "../src/index.ts";
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
test("StrictMode Hook values follow updates/name changes, commands stay immutable, unmount clears", async () => {
 const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: "https://business.example/" });
 Object.assign(globalThis, { window: dom.window, document: dom.window.document, Node: dom.window.Node, HTMLElement: dom.window.HTMLElement });
 const root = createRoot(dom.window.document.getElementById("root")!);
 const session="11111111-1111-4111-8111-111111111111", task="22222222-2222-4222-8222-222222222222", binding="33333333-3333-4333-8333-333333333333";
 const bodies: any[] = [];
 const config = { mode: "bff" as const, clientStateVersion: 1 as const, surfaceMetadataVersion: 1 as const, baseUrl: "/api/agent/surface", clientSessionId: session, controller: false, taskId: task, runId: "run-1", runBindingId: binding, clientBindingDigest: "b".repeat(64), actionContractDigests: {}, initialUiRevision: 0,
 fetchImpl: (async (url, init) => {
  if (String(url).endsWith('/mount')) { const m=JSON.parse(String(init?.body)); return Response.json({ client_surface_metadata_contract_version:1, profile_digest:m.profile_digest, ui_revision:m.ui_revision, mounted_snapshot_digest:'e'.repeat(64), binding_mounted_snapshot_digest:'e'.repeat(64), binding_id:binding, binding_revision:m.ui_revision, binding_digest:String(m.ui_revision).repeat(64), allowed_actions:[], action_contract_digests:{}, controller:false }); }
  if(String(url).endsWith('/commands')) { bodies.push(JSON.parse(String(init?.body))); return Response.json({status:'accepted',commandId:'44444444-4444-4444-8444-444444444444'}); }
  return Response.json({effects:[]});
 }) as typeof fetch };
 let submit!: ReturnType<typeof useZebraReadableCommand>;
 function Readable({name,value}: {name:string;value:string}) { useZebraReadable(name,{route:value}); return null; }
 function Panel({name,value,show}: {name:string;value:string;show:boolean}) { submit=useZebraReadableCommand(); return show ? createElement(Readable,{name,value}) : null; }
 const render=(name:string,value:string,show=true)=>createElement(StrictMode,null,createElement(ZebraAgentProvider,{config,frontendAppId:'fixture-web',profileRevision:1,profileDigest:'c'.repeat(64),children:createElement(Panel,{name,value,show})}));
 try {
  await act(async()=>{root.render(render('app.ui.route','/one'));await new Promise(r=>setTimeout(r,20));});
  await submit({action:'run',expectedRevision:2,idempotencyKey:'one'});
  await act(async()=>{root.render(render('app.ui.route','/two'));await new Promise(r=>setTimeout(r,20));});
  await submit({action:'run',expectedRevision:3,idempotencyKey:'two'});
  await act(async()=>{root.render(render('app.ui.selection','/three'));await new Promise(r=>setTimeout(r,20));});
  await submit({action:'run',expectedRevision:4,idempotencyKey:'three'});
  await act(async()=>{root.render(render('app.ui.selection','/three',false));await new Promise(r=>setTimeout(r,20));});
  await submit({action:'run',expectedRevision:5,idempotencyKey:'clear'});
  assert.deepEqual(bodies.map(b=>b.input.state),[{'app.ui.route':{route:'/one'}},{'app.ui.route':{route:'/two'}},{'app.ui.selection':{route:'/three'}},{}]);
  assert.equal(JSON.stringify(dom.window.sessionStorage).includes('/one'),false);
 } finally { await act(async()=>{root.unmount();await Promise.resolve();});dom.window.close(); }
});

test("initial React Hooks capture once after StrictMode commit and adopt without a remote mount", async () => {
 const {useZebraInitialSurface,useZebraInitialReadable,useZebraInitialAction}=await import('../src/index.ts');
 const {ZebraClientRuntime}=await import('@zebra-agent/client-core');const {z}=await import('zod');
 const dom=new JSDOM('<!doctype html><div id="initial"></div>',{url:'https://business.example/'});
 Object.assign(globalThis,{window:dom.window,document:dom.window.document,Node:dom.window.Node,HTMLElement:dom.window.HTMLElement});
 const root=createRoot(dom.window.document.getElementById('initial')!);
 let surface!:ReturnType<typeof useZebraInitialSurface>;let calls=0;
 const schema=z.object({});
 function Panel({route}:{route:string}){surface=useZebraInitialSurface();useZebraInitialReadable(surface,'app.ui.route',{route});useZebraInitialAction(surface,'app.ui.item.open',{parameters:schema,result:schema,handler:()=>({})});return null;}
 const config={mode:'bff' as const,surfaceMetadataVersion:1 as const,clientStateVersion:1 as const,baseUrl:'/surface',clientSessionId:'11111111-1111-4111-8111-111111111111',taskId:'22222222-2222-4222-8222-222222222222',runId:'run-1',runBindingId:'33333333-3333-4333-8333-333333333333',controller:true,clientBindingDigest:'b'.repeat(64),actionContractDigests:{'app.ui.item.open':'a'.repeat(64)},initialUiRevision:1,fetchImpl:(async()=>{calls++;return Response.json({effects:[]});}) as typeof fetch};
 const metadata={client_surface_metadata_contract_version:1,profile_digest:'c'.repeat(64),ui_revision:1,mounted_snapshot_digest:'d'.repeat(64),binding_mounted_snapshot_digest:'d'.repeat(64),binding_id:config.runBindingId,binding_digest:config.clientBindingDigest,binding_revision:1,allowed_actions:['app.ui.item.open'],action_contract_digests:config.actionContractDigests,controller:true};
 const profile={frontendAppId:'fixture-web',profileRevision:1,profileDigest:'c'.repeat(64)};
 try{
  await act(async()=>{root.render(createElement(StrictMode,null,createElement(Panel,{route:'/one'})));await Promise.resolve();});
  assert.equal(calls,0);const captured=surface.capture();assert.deepEqual(captured.input.state,{'app.ui.route':{route:'/one'}});assert.throws(()=>surface.capture());
  (captured.input.state['app.ui.route'] as Record<string,unknown>).route='/tampered';
  const runtime=ZebraClientRuntime.fromConfig(config);surface.adopt(runtime,metadata,profile);assert.equal(calls,0);assert.equal(runtime.isStopped,false);
  assert.throws(()=>surface.adopt(runtime,metadata,profile));assert.equal(runtime.isStopped,false,'duplicate adoption must not disconnect the already owned runtime');
  const duplicate=ZebraClientRuntime.fromConfig(config);assert.throws(()=>surface.adopt(duplicate,metadata,profile));assert.equal(duplicate.isStopped,true);assert.equal(calls,0,'unadopted duplicate must not release the active Controller');assert.equal(runtime.isStopped,false);
  await act(async()=>{root.render(createElement(StrictMode,null,createElement(Panel,{route:'/changed'})));await Promise.resolve();});
  assert.equal(runtime.isStopped,true);assert.equal(calls,1,'drift releases only the known adopted owner');assert.throws(()=>surface.capture());
  const late=ZebraClientRuntime.fromConfig(config);assert.throws(()=>surface.adopt(late,metadata,profile));assert.equal(calls,1);
 }finally{await act(async()=>{root.unmount();await Promise.resolve();});dom.window.close();}
});

test("initial Hook owner rejects capture before commit and late adoption after unmount", async()=>{
 const {useZebraInitialSurface,useZebraInitialReadable}=await import('../src/index.ts');
 const {ZebraClientRuntime}=await import('@zebra-agent/client-core');
 const dom=new JSDOM('<div id="initial"></div>');Object.assign(globalThis,{window:dom.window,document:dom.window.document});const root=createRoot(dom.window.document.getElementById('initial')!);
 let surface!:ReturnType<typeof useZebraInitialSurface>;let calls=0;
 function Panel(){surface=useZebraInitialSurface();assert.throws(()=>surface.capture());useZebraInitialReadable(surface,'app.ui.route',{route:'/one'});return null;}
 await act(async()=>root.render(createElement(StrictMode,null,createElement(Panel))));surface.capture();await act(async()=>{root.unmount();await Promise.resolve();});
 const runtime=new ZebraClientRuntime({mode:'bff',controller:true,clientSessionId:'owned',baseUrl:'/surface',fetchImpl:(async()=>{calls++;return Response.json({});}) as typeof fetch});
 assert.throws(()=>surface.adopt(runtime,{}, {frontendAppId:'app',profileRevision:1,profileDigest:'c'.repeat(64)}));assert.equal(runtime.isStopped,true);assert.equal(calls,0);dom.window.close();
});

test("duplicate initial Readables reject the whole page rather than silently overwriting a Hook", async()=>{
 const {useZebraInitialSurface,useZebraInitialReadable}=await import('../src/index.ts');
 const dom=new JSDOM('<div id="duplicate"></div>');Object.assign(globalThis,{window:dom.window,document:dom.window.document});const root=createRoot(dom.window.document.getElementById('duplicate')!);
 let surface!:ReturnType<typeof useZebraInitialSurface>;
 function Panel(){surface=useZebraInitialSurface();useZebraInitialReadable(surface,'app.ui.route',{route:'/one'});useZebraInitialReadable(surface,'app.ui.route',{route:'/other'});return null;}
 try{await assert.rejects(async()=>{await act(async()=>root.render(createElement(StrictMode,null,createElement(Panel))));});assert.throws(()=>surface.capture());}
 finally{await act(async()=>{root.unmount();await Promise.resolve();});dom.window.close();}
});

test("explicit React revision pins prior coordinates, adopts once and submits its committed values without remount",async()=>{
 const {useZebraSurfaceRevision,useZebraInitialReadable,useZebraInitialAction}=await import('../src/index.ts');const {z}=await import('zod');
 const dom=new JSDOM('<div id="revision"></div>',{url:'https://business.example/'});Object.assign(globalThis,{window:dom.window,document:dom.window.document});const root=createRoot(dom.window.document.getElementById('revision')!);
 const requests:{url:string;body:any}[]=[];const schema=z.object({});
 const baseConfig={mode:'bff' as const,surfaceMetadataVersion:1 as const,clientStateVersion:1 as const,baseUrl:'/surface',controller:true,clientSessionId:'11111111-1111-4111-8111-111111111111',taskId:'22222222-2222-4222-8222-222222222222',runId:'run-1',runBindingId:'33333333-3333-4333-8333-333333333333',clientBindingDigest:'b'.repeat(64),initialUiRevision:1,actionContractDigests:{'app.ui.item.open':'a'.repeat(64)},fetchImpl:(async(url,init)=>{requests.push({url:String(url),body:JSON.parse(String(init?.body??'null'))});return Response.json(String(url).endsWith('/commands')?{status:'accepted',commandId:'44444444-4444-4444-8444-444444444444'}:{effects:[]});}) as typeof fetch};
 const old={client_surface_metadata_contract_version:1,profile_digest:'c'.repeat(64),ui_revision:1,mounted_snapshot_digest:'d'.repeat(64),binding_mounted_snapshot_digest:'d'.repeat(64),binding_id:baseConfig.runBindingId,binding_digest:baseConfig.clientBindingDigest,binding_revision:1,allowed_actions:['app.ui.item.open'],action_contract_digests:baseConfig.actionContractDigests,controller:true};
 const next={...old,ui_revision:2,binding_revision:2,binding_digest:'e'.repeat(64),mounted_snapshot_digest:'f'.repeat(64),binding_mounted_snapshot_digest:'f'.repeat(64)},config={...baseConfig,initialUiRevision:2,clientBindingDigest:next.binding_digest},profile={frontendAppId:'fixture-web',profileRevision:1,profileDigest:old.profile_digest};
 let revision!:ReturnType<typeof useZebraSurfaceRevision>;
 function Panel({route}:{route:string}){revision=useZebraSurfaceRevision({config:baseConfig,publicMetadata:old,profile});useZebraInitialReadable(revision.surface,'app.ui.route',{route});useZebraInitialAction(revision.surface,'app.ui.item.open',{parameters:schema,result:schema,handler:()=>({})});return null;}
 try{
  await act(async()=>root.render(createElement(StrictMode,null,createElement(Panel,{route:'/revision-two'}))));
  const capture=revision.surface.capture();assert.throws(()=>revision.surface.capture());(capture.input.state['app.ui.route'] as any).route='/mutated';
  for(const changed of [{taskId:baseConfig.clientSessionId},{runId:'other'},{clientSessionId:baseConfig.taskId},{runBindingId:baseConfig.taskId},{baseUrl:'/foreign'}])assert.throws(()=>revision.adopt({...config,...changed},next,profile));
  for(const changed of [{ui_revision:1},{ui_revision:3},{binding_revision:1},{binding_digest:old.binding_digest},{profile_digest:'f'.repeat(64)},{allowed_actions:['foreign.ui.open'],action_contract_digests:{'foreign.ui.open':'a'.repeat(64)}}])assert.throws(()=>revision.adopt(config,{...next,...changed},profile));
  assert.throws(()=>revision.adopt(config,next,{...profile,frontendAppId:"foreign"}));assert.throws(()=>revision.adopt(config,next,{...profile,profileRevision:2}));
  assert.equal(requests.length,0);
  const originalRun=baseConfig.runId;old.binding_digest='0'.repeat(64);baseConfig.runId='caller-mutated';
  const runtime=revision.adopt(config,next,profile);old.binding_digest=baseConfig.clientBindingDigest;baseConfig.runId=originalRun;assert.equal(requests.length,0);assert.equal(runtime.uiRevision.current,2);assert.equal(runtime.isStopped,false);
  assert.throws(()=>revision.adopt(config,next,profile));assert.equal(runtime.isStopped,false);assert.equal(requests.length,0);
  await runtime.submitReadableCommand({action:'run',expectedRevision:2,idempotencyKey:'new-command'});
  assert.deepEqual(requests[0]?.body.input.state,{'app.ui.route':{route:'/revision-two'}});assert.equal(requests.length,1);assert.ok(requests.every(r=>!r.url.endsWith('/mount')));
  await act(async()=>root.render(createElement(StrictMode,null,createElement(Panel,{route:'/drift'}))));assert.equal(runtime.isStopped,true);assert.equal(requests.filter(r=>r.url.endsWith('/release')).length,1);
  assert.throws(()=>revision.adopt(config,next,profile));assert.equal(requests.filter(r=>r.url.endsWith('/release')).length,1);
 }finally{await act(async()=>{root.unmount();await Promise.resolve();});dom.window.close();}
});

test("explicit React revision rejects late adoption and preserves pending original command markers",async()=>{
 const {useZebraSurfaceRevision,useZebraInitialReadable}=await import('../src/index.ts');
 const dom=new JSDOM('<div id="revision"></div>',{url:'https://business.example/'});Object.assign(globalThis,{window:dom.window,document:dom.window.document});let root=createRoot(dom.window.document.getElementById('revision')!);let calls=0;
 const config={mode:'bff' as const,surfaceMetadataVersion:1 as const,clientStateVersion:1 as const,commandRecoveryVersion:1 as const,baseUrl:'/surface',controller:true,clientSessionId:'11111111-1111-4111-8111-111111111111',taskId:'22222222-2222-4222-8222-222222222222',runId:'run-1',runBindingId:'33333333-3333-4333-8333-333333333333',clientBindingDigest:'b'.repeat(64),initialUiRevision:1,actionContractDigests:{},storage:dom.window.sessionStorage,fetchImpl:(async()=>{calls++;return Response.json({});}) as typeof fetch};
 const old={client_surface_metadata_contract_version:1,profile_digest:'c'.repeat(64),ui_revision:1,mounted_snapshot_digest:'d'.repeat(64),binding_mounted_snapshot_digest:'d'.repeat(64),binding_id:config.runBindingId,binding_digest:config.clientBindingDigest,binding_revision:1,allowed_actions:[],action_contract_digests:{},controller:true};
 const next={...old,ui_revision:2,binding_revision:2,binding_digest:'e'.repeat(64)},nextConfig={...config,initialUiRevision:2,clientBindingDigest:next.binding_digest},profile={frontendAppId:'app',profileRevision:1,profileDigest:old.profile_digest};
 let revision!:ReturnType<typeof useZebraSurfaceRevision>;
 function Panel(){revision=useZebraSurfaceRevision({config,publicMetadata:old,profile});useZebraInitialReadable(revision.surface,'app.ui.route',{route:'/two'});return null;}
 await act(async()=>root.render(createElement(StrictMode,null,createElement(Panel))));revision.surface.capture();await act(async()=>{root.unmount();await Promise.resolve();});assert.throws(()=>revision.adopt(nextConfig,next,profile));assert.equal(calls,0);
 root=createRoot(dom.window.document.getElementById('revision')!);await act(async()=>root.render(createElement(StrictMode,null,createElement(Panel))));revision.surface.capture();
 const key=`zebra:command-recovery:${config.clientSessionId}:${config.taskId}:${config.runId}`,pending=JSON.stringify(['44444444-4444-4444-8444-444444444444']);dom.window.sessionStorage.setItem(key,pending);
 assert.throws(()=>revision.adopt(nextConfig,next,profile));assert.equal(dom.window.sessionStorage.getItem(key),pending);assert.equal(calls,0);
 await act(async()=>{root.unmount();await Promise.resolve();});dom.window.close();
});
