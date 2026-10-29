import assert from "node:assert/strict";
import test from "node:test";
import type { RunAgentInput } from "@ag-ui/core";
import { createNativeAgUiTransport } from "../src/agui_native.js";

const operation = "11111111-1111-4111-8111-111111111111";
const effect = "11111111-1111-4111-8111-111111111112";
const oldRun = "agui:" + "a".repeat(64), nextRun = "agui:" + "b".repeat(64);
const input: RunAgentInput = {threadId:"task",runId:oldRun,messages:[],state:{},tools:[],context:[],forwardedProps:{}};

test("revision-two native effect intent captures once and cold GET preserves its original source", async () => {
  const requests: {url:string;method:string;key:string|null;revision:string|null;body:unknown}[] = [];
  const transport = (cold=false) => createNativeAgUiTransport({
    origin:"http://127.0.0.1:12345",publicPath:"/observe",taskId:"task",internalRunId:"native",segmentId:"segment",
    expectedRevision:4,profile:"agui-standard-1.0",revision:2,
    ...(cold ? {originalOperation:operation} : {}),
    interaction:{effectId:effect,receipt:{effect_id:effect,request_digest:"c".repeat(64),status:"succeeded",result:{},
      idempotency_key:"native-effect",controller:true,received_at:"2026-10-29T00:00:00Z"}},
    headers:async write => ({Authorization:write ? "fresh-controller" : "fresh-reader"}),
    fetch:async (url,init) => {
      const headers = new Headers(init?.headers);
      requests.push({url:String(url),method:init?.method ?? "GET",key:headers.get("Idempotency-Key"),
        revision:headers.get("X-Zebra-AGUI-Revision"),body:init?.body ? JSON.parse(String(init.body)) : null});
      if (String(url).endsWith("/stream")) return new Response("data: {}\n\n",{headers:{"Content-Type":"text/event-stream"}});
      return Response.json({status:"prepared",sourceKey:"client-effect-resume:"+effect,input:{...input,runId:nextRun}});
    },
  });
  const native = transport();
  const prepared = await native.admit(operation,input);
  assert.ok(!("pending" in prepared)); assert.equal(prepared.input.runId,nextRun);
  assert.equal(requests[0]!.key,operation); assert.equal(requests[0]!.revision,"2");
  assert.ok(requests[0]!.url.endsWith("/interaction"));
  assert.equal((requests[0]!.body as {receipt:{receipt_id:string}}).receipt.receipt_id,operation);
  await assert.rejects(native.admit(operation,input),/once/);
  await transport(true).receipt(operation);
  assert.equal(requests[1]!.method,"GET"); assert.equal(requests[1]!.key,operation);
  const cold = transport(true);
  await cold.fetch("/observe",{method:"POST",body:JSON.stringify({...input,runId:nextRun})});
  assert.equal(requests.at(-1)!.key,"client-effect-resume:"+effect);
  assert.equal(requests.filter(value=>value.method==="POST" && value.url.endsWith("/interaction")).length,1);
});

test("actual revision-two partial producer preserves classification through official END metadata merge and cold restore", async () => {
  const {execFileSync} = await import("node:child_process");
  const {fileURLToPath} = await import("node:url");
  const root = fileURLToPath(new URL("../../../../../", import.meta.url));
  const recording = JSON.parse(execFileSync(root+".venv/bin/python",["-c",
    "import json; from tests.agent_integrations.test_ag_ui_native_interaction import partial_publication_recording; print(json.dumps(partial_publication_recording()))"],{cwd:root,encoding:"utf8"}));
  const {StandardAgUiConsumer} = await import("../src/agui_reducer.js");
  const binding={threadId:recording.threadId,runId:recording.runId};
  const consumer=new StandardAgUiConsumer(binding);
  await consumer.consume(recording.frames);
  const message=consumer.snapshot.messages.find(message=>message.role==="assistant" && message.content==="Published progress.");
  assert.ok(message);
  assert.deepEqual((message.metadata as {zebra:unknown}).zebra,{
    version:2,kind:"commentary",meaningful:false,evidence_refs:[],
    publicationComplete:false,committed:false,reason:"protocol_slice_ended",
  });
});
