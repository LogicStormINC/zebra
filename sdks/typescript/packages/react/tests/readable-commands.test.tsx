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
