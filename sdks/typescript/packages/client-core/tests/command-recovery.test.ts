import assert from "node:assert/strict";
import {test} from "node:test";
import {ZebraClientRuntime} from "../src/index.ts";
const sid="11111111-1111-4111-8111-111111111111",tid="22222222-2222-4222-8222-222222222222",bid="33333333-3333-4333-8333-333333333333",key="44444444-4444-4444-8444-444444444444",cid="55555555-5555-4555-8555-555555555555";
const options={frontendAppId:"web",profileRevision:1,profileDigest:"c".repeat(64),mountedActions:[],mountedReadables:["app.ui.route"]};
const meta=(revision:number)=>({client_surface_metadata_contract_version:1,profile_digest:options.profileDigest,ui_revision:revision,mounted_snapshot_digest:"e".repeat(64),binding_mounted_snapshot_digest:"e".repeat(64),binding_id:bid,binding_revision:revision,binding_digest:String(revision).repeat(64),allowed_actions:[],action_contract_digests:{},controller:false});
function storage(){const values=new Map<string,string>();return {values,getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>{values.set(k,v);},removeItem:(k:string)=>{values.delete(k);},clear:()=>values.clear(),key:()=>null,length:0} as Storage & {values:Map<string,string>};}
function config(store:Storage,request:typeof fetch){return {mode:"bff" as const,clientStateVersion:1 as const,surfaceMetadataVersion:1 as const,commandRecoveryVersion:1 as const,baseUrl:"/api/agent/surface",clientSessionId:sid,controller:false,taskId:tid,runId:"run-1",runBindingId:bid,clientBindingDigest:"b".repeat(64),actionContractDigests:{},initialUiRevision:0,storage:store,fetchImpl:request};}
const command={action:"run" as const,expectedRevision:2,idempotencyKey:key,input:{messages:[]}};
test("reload blocks remount/dispatch until original receipt accepted, never resends",async()=>{
 const store=storage();let posts=0;let accepted=false;const requests:RequestInit[]=[];
 const request:typeof fetch=async(url,init)=>{requests.push(init!);if(String(url).endsWith('/mount'))return Response.json(meta(JSON.parse(String(init?.body)).ui_revision));if(init?.method==='GET')return Response.json(accepted?{status:'accepted',commandId:cid}:{status:'unknown'});posts++;throw Error('lost reply');};
 const first=ZebraClientRuntime.fromConfig(config(store,request));first.mountReadable('app.ui.route',{route:'/private-page'});await first.mount(options);await assert.rejects(first.submitReadableCommand(command));assert.equal(first.isStopped,true);assert.deepEqual(first.readableCommandRecovery!.pending(),[key]);assert.ok(!JSON.stringify([...store.values]).includes('/private-page'));
 const reload=ZebraClientRuntime.fromConfig(config(store,request));assert.equal(reload.isStopped,true);const count=requests.length;await reload.start();reload.stop();assert.equal(requests.length,count);await assert.rejects(reload.mount(options));await assert.rejects(reload.submitReadableCommand(command));assert.deepEqual(await reload.readableCommandRecovery!.reconcile(key),{status:'unknown'});assert.deepEqual(reload.readableCommandRecovery!.pending(),[key]);
 accepted=true;assert.deepEqual(await reload.readableCommandRecovery!.reconcile(key),{status:'accepted',commandId:cid});assert.deepEqual(reload.readableCommandRecovery!.pending(),[]);assert.equal(posts,1);assert.equal(first.isStopped,true);await assert.rejects(reload.mount(options));const fresh=ZebraClientRuntime.fromConfig(config(store,request));await fresh.mount(options);fresh.disconnect();
 assert.ok(requests.filter(r=>r.method==='GET').every(r=>r.body===undefined&&r.credentials==='same-origin'&&r.cache==='no-store'));
});
test("storage failure blocks POST; invalid input leaves no phantom marker",async()=>{
 const store=storage();let posts=0;const rt=ZebraClientRuntime.fromConfig(config(store,async(url,init)=>{if(String(url).endsWith('/mount'))return Response.json(meta(JSON.parse(String(init?.body)).ui_revision));posts++;return Response.json({status:'accepted',commandId:cid});}));await rt.mount(options);
 await assert.rejects(rt.submitReadableCommand({...command,input:{tools:[]} as never}));assert.deepEqual(rt.readableCommandRecovery!.pending(),[]);store.setItem=()=>{throw Error('quota');};await assert.rejects(rt.submitReadableCommand(command));assert.equal(posts,0);rt.disconnect();
 const corrupt=storage();corrupt.getItem=()=>'{bad';assert.throws(()=>ZebraClientRuntime.fromConfig(config(corrupt,fetch)));
});
test("malformed receipts retain unknown and never retry POST",async()=>{
 for(const body of [{status:'not_observed'},{status:'accepted'},{status:'accepted',commandId:'00000000-0000-0000-0000-000000000000'},{status:'accepted',commandId:cid,credential:'secret'},[],null]){
 const store=storage();let posts=0;const rt=ZebraClientRuntime.fromConfig(config(store,async(url,init)=>String(url).endsWith('/mount')?Response.json(meta(1)):init?.method==='GET'?Response.json(body):(posts++,new Response('',{status:503}))));await rt.mount(options);await assert.rejects(rt.submitReadableCommand(command));await assert.rejects(rt.readableCommandRecovery!.reconcile(key));assert.deepEqual(rt.readableCommandRecovery!.pending(),[key]);assert.equal(posts,1);
 }
});
test("concurrent commands dispatch once, accepted clears only its marker",async()=>{
 const store=storage();let complete!:(r:Response)=>void;let posts=0;const rt=ZebraClientRuntime.fromConfig(config(store,async(url)=>String(url).endsWith('/mount')?Response.json(meta(1)):(posts++,new Promise<Response>(r=>{complete=r;}))));await rt.mount(options);
 const pending=rt.submitReadableCommand(command);await new Promise(r=>setTimeout(r,0));await assert.rejects(rt.submitReadableCommand({...command,idempotencyKey:cid}));complete(Response.json({status:'accepted',commandId:cid}));assert.equal((await pending).commandId,cid);assert.equal(posts,1);assert.deepEqual(rt.readableCommandRecovery!.pending(),[]);rt.disconnect();
});
