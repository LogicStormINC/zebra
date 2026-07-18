import { createServer } from "node:http";

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function responsePlan(messages) {
  const prompt = [...messages].reverse().find((message) => message.role === "user")?.content ?? "";
  const approvalRequested = messages.some(
    (message) => message.role === "user" && String(message.content ?? "").includes("E2E_APPROVAL"),
  );
  if (approvalRequested && messages.some((message) => message.role === "tool")) {
    return { chunks: ["APPROVAL_COMPLETE"], delayMs: 0 };
  }
  if (approvalRequested) {
    return {
      chunks: [],
      delayMs: 0,
      toolCall: {
        id: "call-packaged-approval",
        name: "command__run",
        arguments: JSON.stringify({ command: ["/usr/bin/true"] }),
      },
    };
  }
  if (prompt.includes("E2E_FAILURE")) {
    return { chunks: ["provider-rejected"], delayMs: 0, finishReason: "content_filter" };
  }
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
  if (plan.finishReason === "content_filter") {
    response.writeHead(500, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: { message: "packaged provider failure" } }));
    return;
  }
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
  if (plan.toolCall) {
    response.write(`data: ${JSON.stringify({
      id: "e2e-completion",
      object: "chat.completion.chunk",
      created: 1,
      model: "e2e-stream",
      choices: [{
        index: 0,
        delta: { tool_calls: [{
          index: 0,
          id: plan.toolCall.id,
          type: "function",
          function: { name: plan.toolCall.name, arguments: plan.toolCall.arguments },
        }] },
        finish_reason: null,
      }],
    })}\n\n`);
    response.write(`data: ${JSON.stringify(chunkPayload("", "tool_calls", {
      prompt_tokens: 8,
      completion_tokens: 1,
      total_tokens: 9,
    }))}\n\n`);
    response.end("data: [DONE]\n\n");
    return;
  }
  for (const content of plan.chunks) {
    if (response.destroyed) return;
    response.write(`data: ${JSON.stringify(chunkPayload(content))}\n\n`);
    if (plan.delayMs) await delay(plan.delayMs);
  }
  if (response.destroyed) return;
  const usage = { prompt_tokens: 8, completion_tokens: plan.chunks.length, total_tokens: 8 + plan.chunks.length };
  response.write(`data: ${JSON.stringify(chunkPayload("", plan.finishReason ?? "stop", usage))}\n\n`);
  response.end("data: [DONE]\n\n");
});

server.listen(14_010, "127.0.0.1");
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.close());
