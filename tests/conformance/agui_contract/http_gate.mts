import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { HttpAgent } from "../../../sdks/typescript/packages/client-core/node_modules/@ag-ui/client/dist/index.mjs";
import { createAgUiHttpClient } from "../../../sdks/typescript/packages/client-core/src/agui_http.js";
import { createNativeAgUiTransport } from "../../../sdks/typescript/packages/client-core/src/agui_native.js";
const metadata = JSON.parse(await readFile(process.argv[2]!, "utf8"));
function native(operation?: string) {
  return createNativeAgUiTransport({ ...metadata, publicPath: "/observe", profile: "agui-standard-1.0",
    ...(operation ? { originalOperation: operation } : {}), headers: async () => metadata.headers });
}
let originalOperation = "", admissionPosts = 0;
const client = createAgUiHttpClient({ url: "/observe",
  admit: async (operation, input) => {
    admissionPosts++; originalOperation = operation;
    await native().admit(operation, input);
    throw new Error("Simulated lost original admission response");
  },
  receipt: operation => native(operation).receipt(operation),
  fetch: (url, init) => native(originalOperation).fetch(url, init),
});
await assert.rejects(client.admit(metadata.input), /lost original/);
let outcome = await client.reconcile();
const deadline = Date.now() + 10_000;
while ("pending" in outcome) {
  assert.ok(Date.now() < deadline, "native projector did not prepare original admission");
  await new Promise(resolve => setTimeout(resolve, 20));
  outcome = await client.reconcile();
}
assert.equal(outcome.input.messages.at(-1)?.content, "ACTUAL NEW MESSAGE TO THE MODEL");
assert.match(outcome.input.runId, /^agui:[a-f0-9]{64}$/);
const denied = await fetch(metadata.origin + `/agui/threads/${metadata.taskId}/runs/run-1/stream`, {method:"POST",body:JSON.stringify(outcome.input),headers:{"Content-Type":"application/json"}});
assert.equal(denied.status, 401);
const agent = await client.observe();
assert.ok(agent instanceof HttpAgent);
assert.equal(agent.messages[0]?.content, "ACTUAL NEW MESSAGE TO THE MODEL");
assert.equal(agent.messages.at(-1)?.content, "Worker completed the session.");
assert.equal(agent.isRunning, false);

assert.equal(admissionPosts, 1);
