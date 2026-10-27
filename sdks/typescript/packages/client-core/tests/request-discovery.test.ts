import {test} from "node:test";
import assert from "node:assert/strict";
import {createCommandRecoveryInbox} from "../src/request_discovery.ts";
const key="44444444-4444-4444-8444-000000000001";
const item={key,status:"unknown",handling:{revision:0,action:"",reason:""}};
test("new device discovers without Storage/bootstrap/native credentials, manual handling keeps unknown blocking",async()=>{
 const calls:{path:string;init:RequestInit}[]=[];
 let handled=false;
 const inbox=createCommandRecoveryInbox({path:"/bff/recovery",fetch:async(path,init)=>{
  calls.push({path:String(path),init:init!});
  if(String(path).endsWith("/handling")){handled=true;return Response.json({revision:1,action:"escalate",reason:"unobservable"});}
  if(String(path).endsWith("/receipt"))return Response.json({status:"unknown"});
  return Response.json({items:[handled?{...item,handling:{revision:1,action:"escalate",reason:"unobservable"}}:item],next:""});
 }});
 assert.equal((await inbox.discover()).items[0]!.key,key);
 await assert.rejects(inbox.assertClear(),{code:"command_recovery_pending"});
 assert.deepEqual(await inbox.reconcile(key),{status:"unknown"});
 await inbox.handle(key,{revision:0,action:"escalate",reason:"unobservable"});
 await assert.rejects(inbox.assertClear(),{code:"command_recovery_pending"});
 assert.equal(calls.filter(c=>c.init.method==="POST").length,1);
 assert.ok(calls.every(c=>c.init.credentials==="same-origin"&&c.init.cache==="no-store"&&c.init.redirect==="error"));
 assert.ok(calls.every(c=>!JSON.stringify(c).includes("Client-Session")));
});
test("strict hostile pages, authority leaks, bad cursors and dependency failures stay closed",async()=>{
 for(const data of [{items:[{...item,token:"secret"}],next:""},{items:[item,item],next:""},{items:[item],next:key},{items:[{...item,handling:{revision:0,action:"escalate",reason:"unobservable"}}],next:""},{items:[],next:key},{items:[],next:"",secret:"x"}]){
  const inbox=createCommandRecoveryInbox({path:"/recovery",fetch:async()=>Response.json(data)});
  await assert.rejects(inbox.discover(),{code:"command_recovery_unavailable"});
 }
 for(const path of ["https://evil.invalid","//evil.invalid","/x?secret=x","/x\\evil","/x/"]){assert.throws(()=>createCommandRecoveryInbox({path}));}
 const inbox=createCommandRecoveryInbox({path:"/recovery",fetch:async()=>new Response(null,{status:403})});
 await assert.rejects(inbox.assertClear());await assert.rejects(inbox.reconcile(key));await assert.rejects(inbox.handle(key,{revision:0,action:"escalate",reason:"unobservable"}));
});
test("bounded pagination and stale manual CAS never retry or change the original request",async()=>{
 let posts=0;
 const inbox=createCommandRecoveryInbox({path:"/recovery",fetch:async(path,init)=>{
  if(init?.method==="POST"){posts++;return new Response(null,{status:409});}
  return Response.json({items:[],next:""});
 }});
 await inbox.assertClear();await assert.rejects(inbox.discover("evil"));await assert.rejects(inbox.discover("",51));
 await assert.rejects(inbox.handle(key,{revision:0,action:"escalate",reason:"unobservable"}));assert.equal(posts,1);
});
