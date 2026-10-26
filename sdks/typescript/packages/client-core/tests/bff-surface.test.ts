import assert from "node:assert/strict";
import {test} from "node:test";
import {createBFFSurface} from "../src/bff_surface.ts";
const op="11111111-1111-4111-8111-111111111111";
function memory(): Storage {const m=new Map<string,string>();return {get length(){return m.size},getItem:k=>m.get(k)??null,setItem:(k,v)=>{m.set(k,v)},removeItem:k=>{m.delete(k)},clear:()=>m.clear(),key:i=>[...m.keys()][i]??null};}
const metadata={client_surface_metadata_contract_version:1,profile_digest:"a".repeat(64),ui_revision:2,mounted_snapshot_digest:"b".repeat(64),binding_mounted_snapshot_digest:"b".repeat(64),binding_id:op,binding_digest:"c".repeat(64),binding_revision:1,allowed_actions:["item.save"],action_contract_digests:{"item.save":"d".repeat(64)},controller:true};
function view(operation=op,status="unknown",mappingRevision=2){return {version:"1",status,operation,revision:3,surface:["recorded","installed"].includes(status)?metadata:null,binding:status==="installed"?{mappingRevision,taskId:op,runId:op,clientSessionId:op}:null};}
const captured={mountedActions:["item.save"],mountedReadables:["item.state"],input:{privateValue:"never-store"}};
test("Surface and install losses recreate with GET only; mapping recovery never installs again",async()=>{
 const storage=memory(), methods:string[]=[];let operation="";
 const sdk=createBFFSurface({path:"/surfaces",storage,fetch:async(_u,init)=>{methods.push(init!.method!);operation=new Headers(init!.headers).get("Idempotency-Key")!;assert.ok(!init!.body!.toString().includes("never-store"));throw Error("lost")}});
 await assert.rejects(sdk.submit(captured,2));assert.equal(sdk.pending()!.stage,"surface");await assert.rejects(sdk.submit(captured,2));
 let lost=true;
 const reload=()=>createBFFSurface({path:"/surfaces",storage,fetch:async(u,init)=>{methods.push(init!.method!);if(init!.method==="POST"&&lost){lost=false;throw Error("lost install")};return Response.json(view(operation,u.toString().endsWith("installed")?"installed":"recorded"))}});
 let next=reload();await next.inspect();assert.equal(next.pending()!.stage,"recorded");assert.deepEqual(methods,["POST","GET"]);
 await assert.rejects(next.install(1));assert.equal(next.pending()!.stage,"install");await assert.rejects(next.install(1));
 next=reload();const result=await next.inspect();assert.equal(result.status,"installed");assert.equal(next.pending(),null);assert.deepEqual(methods,["POST","GET","POST","GET"]);
});
test("local loss discovers historical original then explicitly observes existing mapping",async()=>{
 const paths:string[]=[];const sdk=createBFFSurface({path:"/surfaces",storage:memory(),fetch:async u=>{paths.push(u.toString());return Response.json(view(op,u.toString().endsWith("installed")?"installed":"recorded",8))}});
 await sdk.discover();assert.equal(sdk.pending()!.stage,"recorded");assert.equal(paths.length,1);const result=await sdk.observe();assert.equal(result.binding!.mappingRevision,8);assert.equal(sdk.pending(),null);assert.deepEqual(paths,["/surfaces","/surfaces/installed"]);
});
test("unknown and rejected never permit install; absent mapping never changes phase or resends",async()=>{
 const storage=memory();let status="unknown";const sdk=createBFFSurface({path:"/surfaces",storage,fetch:async()=>Response.json(view(op,status))});
 await sdk.discover();await assert.rejects(sdk.install(0));status="rejected";await sdk.inspect();await assert.rejects(sdk.submit(captured,3));await assert.rejects(sdk.install(0));assert.equal(sdk.pending()!.stage,"surface");
 status="recorded";await sdk.inspect();status="unknown";await sdk.install(1);assert.equal(sdk.pending()!.stage,"install");await sdk.inspect();assert.equal(sdk.pending()!.stage,"install");
});
test("storage failure blocks network; only locator and install revision persisted",async()=>{
 const storage=memory();let calls=0;storage.setItem=()=>{throw Error("quota")};const sdk=createBFFSurface({path:"/surfaces",storage,fetch:async()=>{calls++;return Response.json(view())}});await assert.rejects(sdk.submit(captured,1));assert.equal(calls,0);
 storage.getItem=()=>'{"operation":"wrong","stage":"surface"}';assert.throws(()=>createBFFSurface({path:"/surfaces",storage}));
});
test("strict metadata, status, coordinates, extra secrets and unsafe numbers fail closed",async()=>{
 for(const bad of [{...view(),token:"secret"},{...view(),revision:true},{...view(),version:"2"},{...view(op,"recorded"),surface:{...metadata,controller_fence_token:"secret"}},{...view(op,"recorded"),surface:{...metadata,binding_mounted_snapshot_digest:"e".repeat(64)}},{...view(op,"installed"),binding:{mappingRevision:2**53,taskId:op,runId:op,clientSessionId:op}}]){
 const sdk=createBFFSurface({path:"/surfaces",storage:memory(),fetch:async()=>Response.json(bad)});await assert.rejects(sdk.inspect(op));assert.equal(sdk.pending()!.operation,op);
 }
});
test("expected mapping revision and competing discovered originals cannot erase pending",async()=>{
 let result=view(op,"recorded");const storage=memory(),sdk=createBFFSurface({path:"/surfaces",storage,fetch:async()=>Response.json(result)});await sdk.discover();result=view(op,"installed",9);await assert.rejects(sdk.install(1));assert.equal(sdk.pending()!.stage,"install");
 result=view("22222222-2222-4222-8222-222222222222");await assert.rejects(sdk.discover());assert.equal(sdk.pending()!.operation,op);result=view("","clear");await sdk.discover();assert.equal(sdk.pending()!.stage,"install");
});
test("strict names, transport, scope and in-flight guard; preparation sends no Readable values",async()=>{
 let release!:()=>void;const wait=new Promise<void>(r=>{release=r});let operation="";const storage=memory();const sdk=createBFFSurface({path:"/surfaces",storage,fetch:async(_u,init)=>{
 assert.equal(init!.mode,"same-origin");assert.equal(init!.credentials,"same-origin");assert.equal(init!.redirect,"error");assert.equal(init!.cache,"no-store");assert.ok(init!.signal);const h=new Headers(init!.headers);assert.equal(h.get("X-Overdoze-Surface"),"1");assert.equal(h.has("Authorization"),false);operation=h.get("Idempotency-Key")!;assert.deepEqual(JSON.parse(init!.body!.toString()),{revision:2,prepared:{mountedActions:["item.save"],mountedReadables:["item.state"]}});await wait;return Response.json(view(operation,"recorded"));}});
 for(const value of [{...captured,mountedActions:["bad"]},{...captured,mountedActions:["item.save","item.save"]},{...captured,credential:"private"}])await assert.rejects(sdk.submit(value,2));
 const first=sdk.submit(captured,2);await assert.rejects(sdk.discover());assert.ok(!storage.getItem(storage.key(0)!)!.includes("never-store"));release();await first;assert.equal(sdk.pending()!.stage,"recorded");
 for(const path of ["//evil","https://evil","/../x","/surfaces?x=1","/surfaces/"])assert.throws(()=>createBFFSurface({path,storage:memory()}));
});
