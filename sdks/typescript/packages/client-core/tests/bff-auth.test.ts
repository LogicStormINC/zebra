import {test} from "node:test";
import assert from "node:assert/strict";
import {createBFFAuth} from "../src/bff_auth.ts";
const op="11111111-1111-4111-8111-111111111111";
function memory(): Storage {const values=new Map<string,string>();return {getItem:k=>values.get(k)??null,setItem:(k,v)=>{values.set(k,v);},removeItem:k=>{values.delete(k);},clear:()=>values.clear(),key:i=>[...values.keys()][i]??null,get length(){return values.size;}};}
const view=(operation=op,kind="install",outcome="completed",status="active",revision=1)=>({version:"1",status,revision,currentOperation:operation,receipt:{operation,kind,outcome}});
test("explicit refresh stores opaque locator before POST, current status and safe transport",async()=>{
 const storage=memory();let posts=0;
 const auth=createBFFAuth({path:"/bff/auth",storage,fetch:async(url,init)=>{
  assert.equal(init!.credentials,"same-origin");assert.equal(init!.cache,"no-store");assert.equal(init!.redirect,"error");
  assert.equal((init!.headers as Record<string,string>)["X-Overdoze-Auth"],"1");
  if(init!.method==="POST"){
   posts++;const marker=JSON.parse(storage.getItem(storage.key(0)!)!);assert.equal(marker.kind,"refresh");
   assert.equal(marker.operation,(init!.headers as Record<string,string>)["Idempotency-Key"]);assert.deepEqual(JSON.parse(init!.body as string),{revision:1});
   return Response.json(view(marker.operation,"refresh","completed","active",3));
  }
  return Response.json(view());
 }});
 assert.equal((await auth.assertActive()).status,"active");await auth.refresh(1);assert.equal(posts,1);assert.equal(auth.pending(),null);
});
test("lost response survives reload: inspect only, absence stays pending, no automatic resend",async()=>{
 const storage=memory();let posts=0;let outcome="not_observed";
 const request:typeof fetch=async(url,init)=>{
  if(init!.method==="POST"){posts++;throw Error("network lost");}
  const marker=auth.pending()!;
  return Response.json({...view(op,"refresh","unknown","unknown",2),receipt:{operation:marker.operation,kind:outcome==="not_observed"?"":"refresh",outcome}});
 };
 const auth=createBFFAuth({path:"/auth",storage,fetch:request});await assert.rejects(auth.refresh(1));
 const marker=auth.pending()!;const reopened=createBFFAuth({path:"/auth",storage,fetch:request});
 await assert.rejects(reopened.refresh(1),{code:"auth_pending"});await assert.rejects(reopened.assertActive(),{code:"auth_pending"});
 await reopened.inspect(marker.operation);assert.ok(reopened.pending());
 outcome="unknown";await reopened.inspect(marker.operation);assert.ok(reopened.pending());assert.equal(posts,1);
 outcome="completed";await reopened.inspect(marker.operation);assert.equal(reopened.pending(),null);
 await assert.rejects(reopened.assertActive());assert.equal(posts,1);
});
test("unknown only enters explicit retirement, closed then needs fresh business reauth",async()=>{
 const storage=memory();const methods:string[]=[];
 const auth=createBFFAuth({path:"/auth",storage,fetch:async(url,init)=>{
  methods.push(init!.method!);if(String(url).endsWith("/refresh"))throw Error("lost");
  const operation=(init!.headers as Record<string,string>)["Idempotency-Key"];
  if(String(url).endsWith("/retire"))return Response.json(view(operation,"retire","completed","closed",4));
  return Response.json(view(op,"retire","completed","closed",4));
 }});
 await assert.rejects(auth.refresh(1));assert.equal((await auth.retire(2)).status,"closed");assert.equal(auth.pending(),null);
 await assert.rejects(auth.assertActive(),{code:"auth_pending"});assert.deepEqual(methods,["POST","POST","GET"]);
});
test("hostile DTOs, leaked secrets, storage failure and paths fail closed",async()=>{
 for(const value of [{...view(),access_token:"secret"},{...view(),revision:0},{...view(),status:"ready"},{...view(),receipt:{...view().receipt,secret:"x"}},{...view(),currentOperation:"evil"},{...view(),receipt:{...view().receipt,outcome:"unknown"}}]){
  const auth=createBFFAuth({path:"/auth",storage:memory(),fetch:async()=>Response.json(value)});await assert.rejects(auth.assertActive());
 }
 for(const path of ["//evil","https://evil","/auth?x=y","/auth/","/../auth","/auth%2fsecret"]){assert.throws(()=>createBFFAuth({path,storage:memory()}));}
 let calls=0;const storage=memory();storage.setItem=()=>{throw Error("quota");};
 const auth=createBFFAuth({path:"/auth",storage,fetch:async()=>{calls++;return Response.json(view());}});
 await assert.rejects(auth.refresh(1));assert.equal(calls,0);
});
test("malformed/lost/denied/conflicting responses retain marker; in-flight mutations cannot double dispatch",async()=>{
 for(const response of [()=>new Response(null,{status:401}),()=>new Response(null,{status:409}),()=>new Response("x"),()=>Response.json(view()),()=>new Response(" ".repeat(4097))]){
  const auth=createBFFAuth({path:"/auth",storage:memory(),fetch:async()=>response()});await assert.rejects(auth.refresh(1));assert.ok(auth.pending());
 }
 let unblock!:(r:Response)=>void;let calls=0;
 const auth=createBFFAuth({path:"/auth",storage:memory(),fetch:async()=>{calls++;return new Promise<Response>(r=>{unblock=r;});}});
 const first=auth.refresh(1);await assert.rejects(auth.refresh(1));await assert.rejects(auth.retire(1));
 const marker=auth.pending()!;unblock(Response.json(view(marker.operation,"refresh","completed","active",3)));await first;assert.equal(calls,1);
});

test("refresh_required exposes CAS but never passes the bootstrap guard",async()=>{
 const auth=createBFFAuth({path:"/auth",storage:memory(),fetch:async()=>Response.json(view(op,"install","completed","refresh_required"))});
 assert.equal((await auth.state()).revision,1);await assert.rejects(auth.assertActive(),{code:"auth_pending"});
});
