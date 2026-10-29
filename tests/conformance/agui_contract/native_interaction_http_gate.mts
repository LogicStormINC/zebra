/** Actual signed native HTTP -> retained official consumer, never re-admit cold history. */
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {randomUUID,sign} from "node:crypto";
import {HttpAgent} from "../../../sdks/typescript/packages/client-core/node_modules/@ag-ui/client/dist/index.mjs";
import {createAgUiHttpClient} from "../../../sdks/typescript/packages/client-core/src/agui_http.js";
import {createNativeAgUiTransport} from "../../../sdks/typescript/packages/client-core/src/agui_native.js";
import {readReliableAgUiStream} from "../../../sdks/typescript/packages/client-core/src/sse_stream.js";
const metadata = JSON.parse(await readFile(process.argv[2]!,"utf8"));
function headers() {
  const now=Math.floor(Date.now()/1000), c=metadata.context;
  const claims={iss:metadata.issuer,aud:"agui-interaction-gate",sub:metadata.subject,jti:randomUUID(),iat:now-1,nbf:now-1,exp:now+120,
    host_app_id:c.host_app_id,namespace_id:c.namespace_id,workspace_ref:c.workspace_ref,
    resource_refs:c.resource_refs.map((ref:{resource_type:string;resource_id:string})=>({type:ref.resource_type,id:ref.resource_id})),
    scopes:c.scopes,limits:c.limits,origin:c.origin,policy_version:c.policy_version};
  const head=Buffer.from(JSON.stringify({alg:"RS256",typ:"JWT"})).toString("base64url");
  const body=Buffer.from(JSON.stringify(claims)).toString("base64url");
  return {...metadata.headers,Origin:c.origin,Authorization:`Bearer ${head}.${body}.${sign("RSA-SHA256",Buffer.from(head+"."+body),metadata.privateKey).toString("base64url")}`};
}
for (const locator of metadata.locators) {
  let admissions=0, toolResults=0;
  if (locator.readOnly) {
    const observed = new HttpAgent({url:metadata.origin+`/agui/threads/${metadata.taskId}/runs/${metadata.run}/stream`,
      threadId:metadata.taskId, initialMessages:[], initialState:{}, debug:false});
    observed.fetch=async()=>{
      const response=await fetch(metadata.origin+`/agui/threads/${metadata.taskId}/runs/${metadata.run}/stream`,
        {method:"GET",headers:{...headers(),Accept:"text/event-stream","Idempotency-Key":locator.sourceKey}});
      assert.ok(response.ok && response.body);
      return new Response(new ReadableStream({async start(controller){
        try {await readReliableAgUiStream(response.body!,{signal:new AbortController().signal,recovery:{active:true},onCanonical:async event=>{
          controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));}});
          controller.close();} catch(error){controller.error(error);}
      }}),{headers:{"Content-Type":"text/event-stream"}});
    };
    await observed.runAgent({runId:locator.publicRunId},{onEvent:({event})=>{
      if(event.type==="TOOL_CALL_RESULT")toolResults++; }});
    const results=observed.messages.filter(message=>message.role==="tool" && message.toolCallId===locator.toolCallId);
    assert.equal(results.length,1);assert.equal(results[0]!.id,"tool-result:"+locator.toolCallId);
    assert.deepEqual(JSON.parse(results[0]!.content as string),{status:locator.status,result:locator.result});
    assert.equal(toolResults,1);assert.ok(!JSON.stringify(observed.state).includes("private"));
    continue;
  }
  // Rebuild the BFF transport before each read. Neither recovery nor observation
  // has permission to execute a browser action or POST another native intent.
  function native() {return createNativeAgUiTransport({origin:metadata.origin,publicPath:"/observe",taskId:metadata.taskId,
    internalRunId:metadata.run,segmentId:metadata.taskId,expectedRevision:0,profile:metadata.profile,revision:2,
    originalOperation:locator.operation,interaction:{...(locator.effectId ? {effectId:locator.effectId} : {})},headers:async()=>headers()});}
  const prepared=await native().receipt(locator.operation);
  assert.ok(!("pending" in prepared));
  const client=createAgUiHttpClient({url:"/observe",reliable:metadata.profile.startsWith("zebra-reliable"),
    admit:async()=>{admissions++;throw new Error("Cold history must not admit");},
    receipt:op=>native().receipt(op),fetch:(url,init)=>native().fetch(url,init),
    onEvent:event=>{if(event.type==="TOOL_CALL_RESULT")toolResults++;}});
  await client.attachPrepared(prepared);
  const actual=client.agent;
  const agent=await client.observe();
  assert.ok(agent instanceof HttpAgent);assert.equal(agent,actual);assert.equal(admissions,0);
  const ids=agent.messages.map(message=>message.id);
  assert.equal(ids.length,new Set(ids).size,"one canonical message per native identity");
  if(locator.clarificationId) {
    const results=agent.messages.filter(message=>message.role==="tool" && message.toolCallId===locator.clarificationId);
    assert.equal(results.length,1,"actual human answer produces one canonical clarification result");
    assert.equal(results[0]!.id,"tool-result:"+locator.clarificationId);
    assert.deepEqual(JSON.parse(results[0]!.content as string),{
      clarification_id:locator.clarificationId,user_response:locator.answer});
    assert.equal(toolResults,1);
  }
  if(locator.effectId) {
    const results=agent.messages.filter(message=>message.role==="tool" && message.toolCallId===locator.toolCallId);
    assert.equal(results.length,1);assert.equal(results[0]!.id,"tool-result:"+locator.toolCallId);
    assert.deepEqual(JSON.parse(results[0]!.content as string),{status:locator.status,result:locator.result});
    assert.equal(toolResults,1,"public receipt produces one actual result even if initial input already contains it");
    const activity=agent.messages.find(message=>message.id==="execution:"+locator.toolCallId);
    assert.ok(activity && activity.role==="activity","actual application receipt settles the public tool activity");
    assert.equal(activity.content.status,locator.status==="succeeded" ? "completed" : "failed");
    assert.equal(activity.content.client_effect_status,locator.status);
  }
}
