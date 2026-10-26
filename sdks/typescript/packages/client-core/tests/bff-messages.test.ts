import assert from "node:assert/strict";
import {test} from "node:test";
import {createBFFMessages} from "../src/bff_messages.ts";
const op="11111111-1111-4111-8111-111111111111";
function memory(): Storage {const m=new Map<string,string>();return {get length(){return m.size},getItem:k=>m.get(k)??null,setItem:(k,v)=>{m.set(k,v)},removeItem:k=>{m.delete(k)},clear:()=>m.clear(),key:i=>[...m.keys()][i]??null};}
function view(operation=op,status="unknown",revision=2){return {version:"1",status,operation,revision,anchor:status==="recorded"?{receipt_key:operation,request_hash:"a".repeat(64),event_id:op,segment_id:op,segment_sequence:3}:null};}
test("lost POST keeps only locator; reload original GET never resends",async()=>{
 const storage=memory();const methods:string[]=[];let original="";
 const sdk=createBFFMessages({path:"/messages",storage,fetch:async(_u,init)=>{methods.push(init!.method!);original=new Headers(init!.headers).get("Idempotency-Key")!;throw Error("lost");}});
 await assert.rejects(sdk.submit("private text",1));assert.equal(sdk.pending(),original);
 assert.ok(!storage.getItem(storage.key(0)!)!.includes("private text"));await assert.rejects(sdk.submit("retry",1));
 const reload=createBFFMessages({path:"/messages",storage,fetch:async(_u,init)=>{methods.push(init!.method!);assert.equal(new Headers(init!.headers).get("Idempotency-Key"),original);return Response.json(view(original,"recorded"));}});
 await reload.inspect(original);assert.equal(reload.pending(),null);assert.deepEqual(methods,["POST","GET"]);
});
test("unknown and absent receipt retain locator; discover recovers server pending after local loss",async()=>{
 const storage=memory();let calls=0;const sdk=createBFFMessages({path:"/messages",storage,fetch:async()=>{calls++;return Response.json(view());}});
 await sdk.discover();assert.equal(sdk.pending(),op);await sdk.inspect(op);assert.equal(sdk.pending(),op);
 await assert.rejects(sdk.submit("blocked",2));assert.equal(calls,2);
});
test("storage denial blocks dispatch and corrupt locators block construction",async()=>{
 let calls=0;const storage=memory();storage.setItem=()=>{throw Error("quota")};
 const sdk=createBFFMessages({path:"/messages",storage,fetch:async()=>{calls++;return Response.json(view())}});
 await assert.rejects(sdk.submit("text",1));assert.equal(calls,0);
 storage.getItem=()=>'{"operation":"wrong"}';assert.throws(()=>createBFFMessages({path:"/messages",storage}));
});
test("strict states, secret fields, old coordinates and unsafe integers fail closed",async()=>{
 for(const bad of [{...view(),token:"secret"},{...view(),revision:true},{...view(),version:"2"},{...view(),status:"accepted"},{...view(op,"recorded"),anchor:null},{...view(op,"recorded"),anchor:{...view(op,"recorded").anchor,segment_sequence:true}},{...view(op,"recorded"),anchor:{...view(op,"recorded").anchor,segment_sequence:2**53}}]){
  const sdk=createBFFMessages({path:"/messages",storage:memory(),fetch:async()=>Response.json(bad)});await assert.rejects(sdk.inspect(op));assert.equal(sdk.pending(),op);
 }
});
test("same-origin bounded transport never sends credentials or follows redirects",async()=>{
 const sdk=createBFFMessages({path:"/messages",storage:memory(),fetch:async(_u,init)=>{
  assert.equal(init!.mode,"same-origin");assert.equal(init!.credentials,"same-origin");assert.equal(init!.redirect,"error");assert.equal(init!.cache,"no-store");assert.ok(init!.signal);
  const h=new Headers(init!.headers);assert.equal(h.get("X-Overdoze-Message"),"1");assert.equal(h.has("Authorization"),false);assert.equal(h.has("X-Zebra-Client-Session"),false);
  return Response.json(view(h.get("Idempotency-Key")!,"recorded"));
 }});await sdk.submit("原消息 😀",1);assert.equal(sdk.pending(),null);
 for(const path of ["//evil","https://evil","/../x","/messages?x=1","/messages/"])assert.throws(()=>createBFFMessages({path,storage:memory()}));
});
test("competing discovery cannot overwrite unknown and clear does not erase it",async()=>{
 const storage=memory();let result=view();const sdk=createBFFMessages({path:"/messages",storage,fetch:async()=>Response.json(result)});
 await sdk.discover();result=view("22222222-2222-4222-8222-222222222222");await assert.rejects(sdk.discover());assert.equal(sdk.pending(),op);
 result={...view("","clear"),anchor:null};await sdk.discover();assert.equal(sdk.pending(),op);
});

test("invalid Unicode and oversized text reject before persist or network",async()=>{
 let calls=0;const storage=memory(),sdk=createBFFMessages({path:"/messages",storage,fetch:async()=>{calls++;return Response.json(view())}});
 for(const text of ["\ud800","x".repeat(17000)])await assert.rejects(sdk.submit(text,1));assert.equal(calls,0);assert.equal(sdk.pending(),null);
});
