import {test} from "node:test";
import assert from "node:assert/strict";
import {createAuthenticatedRuntime} from "../src/auth_lifecycle.ts";
import {createBFFAuth} from "../src/bff_auth.ts";
const op="11111111-1111-4111-8111-111111111111";
function storage():Storage{const m=new Map<string,string>();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>{m.set(k,v);},removeItem:k=>{m.delete(k);},clear:()=>m.clear(),key:i=>[...m.keys()][i]??null,get length(){return m.size;}};}
function fixture(){
 let status="active",posts=0,boots=0,mounts=0,creates=0,stops=0;
 const auth=createBFFAuth({path:"/auth",storage:storage(),fetch:async(url,init)=>{
  if(init?.method==="POST"){posts++;assert.ok(stops>=creates,"auth mutation preceded Runtime stop");throw Error("lost response");}
  return Response.json({version:"1",status,revision:1,currentOperation:op,receipt:{operation:op,kind:"install",outcome:status==="unknown"?"unknown":"completed"}});
 }});
 const options={auth,bootstrap:async(signal:AbortSignal)=>{assert.equal(signal.aborted,false);boots++;return {fresh:boots};},create:(b:{fresh:number})=>{creates++;let stopped=false;return {fresh:b.fresh,get isStopped(){return stopped;},stop:()=>{if(!stopped)stops++;stopped=true;}};},mount:async()=>{mounts++;}};
 return {auth,options,stats:()=>({posts,boots,mounts,creates,stops}),setStatus:(s:string)=>{status=s;}};
}
test("fresh explicit starts only; refresh stops first, unknown never retries or restarts",async()=>{
 const f=fixture(),life=createAuthenticatedRuntime(f.options);const r=await life.start();assert.equal(r.fresh,1);assert.equal(life.runtime,r);
 await assert.rejects(life.start());await assert.rejects(life.refresh(1));assert.equal(life.runtime,null);assert.equal(f.stats().stops,1);
 await assert.rejects(life.start());await assert.rejects(life.refresh(1));assert.equal(f.stats().posts,1);assert.equal(f.stats().boots,1);
});
test("sync unknown/closed/expired/denied stops and never restarts",async()=>{
 for(const status of ["unknown","closed","refresh_required"]){const f=fixture(),life=createAuthenticatedRuntime(f.options);await life.start();f.setStatus(status);await life.sync();assert.equal(life.runtime,null);assert.equal(f.stats().stops,1);await assert.rejects(life.start());}
 const f=fixture(),life=createAuthenticatedRuntime(f.options);await life.start();f.setStatus("malformed");await assert.rejects(life.sync());assert.equal(life.runtime,null);
});
test("late bootstrap after logout cannot create or mount, even if callback ignored abort",async()=>{
 const f=fixture();let done!:(v:{fresh:number})=>void;
 const life=createAuthenticatedRuntime({...f.options,bootstrap:async()=>new Promise<{fresh:number}>(r=>{done=r;})});
 const start=life.start();while(!done)await new Promise(r=>setImmediate(r));life.stop();done({fresh:1});await assert.rejects(start);
 assert.deepEqual(f.stats(),{posts:0,boots:0,mounts:0,creates:0,stops:0});assert.equal(life.runtime,null);
});
test("late mount completion cannot resurrect stopped Runtime; explicit restart gets fresh bootstrap",async()=>{
 const f=fixture();let done!:()=>void;let wait=true;
 const life=createAuthenticatedRuntime({...f.options,mount:async()=>{if(wait)await new Promise<void>(r=>{done=r;});}});
 const start=life.start();while(!done)await new Promise(r=>setImmediate(r));life.stop();done();await assert.rejects(start);assert.equal(life.runtime,null);assert.equal(f.stats().stops,1);
 wait=false;assert.equal((await life.start()).fresh,2);life.stop();assert.equal(f.stats().stops,2);
});
test("authority lost after mount stops before returning Runtime; bootstrap errors leave no instance",async()=>{
 const f=fixture(),life=createAuthenticatedRuntime({...f.options,mount:async()=>{f.setStatus("closed");}});await assert.rejects(life.start());assert.equal(life.runtime,null);assert.equal(f.stats().stops,1);
 const bad=createAuthenticatedRuntime({...f.options,bootstrap:async()=>{throw Error("unavailable");}});await assert.rejects(bad.start());assert.equal(bad.runtime,null);
});

test("native terminal stop cannot be returned as a successful mount or resurrected",async()=>{
 const f=fixture();const life=createAuthenticatedRuntime({...f.options,mount:async(runtime)=>{runtime.stop();}});
 await assert.rejects(life.start());assert.equal(life.runtime,null);assert.equal(f.stats().stops,1);
 const second=createAuthenticatedRuntime(f.options);const r=await second.start();r.stop();assert.equal(second.runtime,null);
 assert.equal((await second.start()).fresh,3);second.stop();
});
