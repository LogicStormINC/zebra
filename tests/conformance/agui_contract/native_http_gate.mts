import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { randomUUID, sign } from "node:crypto";
import { HttpAgent } from "../../../sdks/typescript/packages/client-core/node_modules/@ag-ui/client/dist/index.mjs";
import { createAgUiHttpClient } from "../../../sdks/typescript/packages/client-core/src/agui_http.js";
import { createNativeAgUiTransport } from "../../../sdks/typescript/packages/client-core/src/agui_native.js";
import { readSseRecords } from "../../../sdks/typescript/packages/client-core/src/sse_records.js";
const metadata = JSON.parse(await readFile(process.argv[2]!, "utf8"));
function headers(run: string) {
  const now = Math.floor(Date.now()/1000), context = metadata.context;
  const claims = { iss:metadata.issuer,aud:"agui-gate",sub:metadata.subject,jti:randomUUID(),iat:now-1,nbf:now-1,exp:now+120,
    host_app_id:context.host_app_id,namespace_id:context.namespace_id,workspace_ref:context.workspace_ref,
    resource_refs:context.resource_refs.map((ref: {type?:string;id?:string;resource_type?:string;resource_id?:string}) => ({type:ref.type ?? ref.resource_type,id:(ref.type ?? ref.resource_type) === "run" ? run : ref.id ?? ref.resource_id})),
    scopes:context.scopes,limits:context.limits,origin:context.origin,policy_version:context.policy_version };
  const head = Buffer.from(JSON.stringify({alg:"RS256",typ:"JWT"})).toString("base64url");
  const body = Buffer.from(JSON.stringify(claims)).toString("base64url");
  const signature = sign("RSA-SHA256",Buffer.from(head+"."+body),metadata.privateKey).toString("base64url");
  return {...metadata.headers,Origin:context.origin,Authorization:`Bearer ${head}.${body}.${signature}`};
}
let previousMessages: unknown[] = [];
for (const [profile, locator] of [["agui-standard-1.0",metadata.initial],["zebra-reliable-v2-agui-1.0",metadata.followup]] as const) {
  let connections = 0, cut = false, texts = 0;
  function native() { return createNativeAgUiTransport({origin:metadata.origin,publicPath:"/observe", taskId:metadata.taskId,
    internalRunId:locator.run,segmentId:metadata.taskId,expectedRevision:0, profile,
    originalOperation:locator.operation, ...(locator.eventKey ? {originalEventKey:locator.eventKey} : {}), headers:async () => headers(locator.run) }); }
  const prepared = await native().receipt(locator.operation);
  assert.ok(!("pending" in prepared));
  const reliable = profile.startsWith("zebra-reliable");
  const client = createAgUiHttpClient({url:"/observe",reliable,
    admit:async () => { throw new Error("An initial prepared receipt must never readmit"); },
    receipt:operation => native().receipt(operation),
    onEvent:event => { if(event.type === "TEXT_MESSAGE_CONTENT") texts++; },
    fetch:async (url,init) => {
      connections++;
      const response = await native().fetch(url,init);
      if (!reliable || cut || !response.ok || !response.body) return response;
      return new Response(new ReadableStream<Uint8Array>({start(controller) {
        void (async () => {
          for await (const record of readSseRecords(response.body!,16384)) {
            controller.enqueue(new TextEncoder().encode(`${record.id ? `id: ${record.id}\n` : ""}data: ${record.data}\n\n`));
            const event = JSON.parse(record.data);
            if(event.name === "zebra.canonical_chunk" && event.value.last === false) {cut=true;break;}
          }
          controller.close();
        })().catch(error => controller.error(error));
      }}),{headers:response.headers});
    },
  });
  await client.attachPrepared(prepared);
  const actual = client.agent;
  const registered: string[] = [];
  actual!.subscribe({onEvent:({event}) => {registered.push(event.type);}});
  const agent = await client.observe();
  assert.ok(agent instanceof HttpAgent); assert.equal(agent,actual);
  assert.equal(agent.messages[0]?.content,"ACTUAL INITIAL USER MESSAGE");
  const actualText = agent.messages.at(-1)?.content, expectedText = reliable ? locator.answer : "Worker completed the session.";
  assert.ok(actualText === expectedText, `actual/expected text lengths ${String(actualText).length}/${expectedText.length}`);
  assert.equal(texts,1); assert.equal(registered.filter(type => type === "RUN_STARTED").length,1);
  if (reliable) {
    assert.ok(cut); assert.equal(connections,2); assert.equal(agent.messages.length,4);
    assert.ok(client.cursor?.startsWith("v2p."));
    assert.equal(agent.messages[0]?.id,(previousMessages[0] as {id:string}).id);
    assert.equal(agent.messages[1]?.id,(previousMessages[1] as {id:string}).id);
  } else { assert.equal(connections,1); previousMessages=structuredClone(agent.messages); }
}
