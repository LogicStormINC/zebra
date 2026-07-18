import { createServer } from "node:http";

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function responsePlan(messages) {
  const prompt = [...messages].reverse().find((message) => message.role === "user")?.content ?? "";
  if (prompt.includes("E2E_STOP_STREAM")) {
    return { chunks: Array.from({ length: 120 }, (_, index) => `stop-${String(index).padStart(3, "0")}|`), delayMs: 40 };
  }
  if (prompt.includes("E2E_RECOVER_STREAM")) {
    return { chunks: Array.from({ length: 80 }, (_, index) => `recover-${String(index).padStart(3, "0")}|`), delayMs: 30 };
  }
  if (prompt.includes("E2E_LONG_STREAM")) {
    return { chunks: Array.from({ length: 64 }, (_, index) => `long-${String(index).padStart(3, "0")}|`), delayMs: 20 };
  }
  if (prompt.includes("E2E_FOLLOW_UP_TWO")) return { chunks: ["SECOND_COMPLETE"], delayMs: 0 };
  return { chunks: ["FIRST_COMPLETE"], delayMs: 0 };
}

function chunkPayload(content, finishReason = null, usage) {
  return {
    id: "e2e-completion",
    object: "chat.completion.chunk",
    created: 1,
    model: "e2e-stream",
    choices: [{ index: 0, delta: content ? { content } : {}, finish_reason: finishReason }],
    ...(usage ? { usage } : {}),
  };
}

const server = createServer(async (request, response) => {
  if (request.method !== "POST" || request.url !== "/chat/completions") {
    response.writeHead(404).end();
    return;
  }
  const buffers = [];
  for await (const buffer of request) buffers.push(buffer);
  const body = JSON.parse(Buffer.concat(buffers).toString("utf8"));
  const plan = responsePlan(Array.isArray(body.messages) ? body.messages : []);
  if (!body.stream) {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({
      id: "e2e-completion",
      model: "e2e-stream",
      choices: [{ index: 0, message: { role: "assistant", content: plan.chunks.join("") }, finish_reason: "stop" }],
      usage: { prompt_tokens: 8, completion_tokens: plan.chunks.length, total_tokens: 8 + plan.chunks.length },
    }));
    return;
  }
  response.writeHead(200, {
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "content-type": "text/event-stream",
  });
  for (const content of plan.chunks) {
    if (response.destroyed) return;
    response.write(`data: ${JSON.stringify(chunkPayload(content))}\n\n`);
    if (plan.delayMs) await delay(plan.delayMs);
  }
  if (response.destroyed) return;
  const usage = { prompt_tokens: 8, completion_tokens: plan.chunks.length, total_tokens: 8 + plan.chunks.length };
  response.write(`data: ${JSON.stringify(chunkPayload("", "stop", usage))}\n\n`);
  response.end("data: [DONE]\n\n");
});

server.listen(14_010, "127.0.0.1");
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.close());
