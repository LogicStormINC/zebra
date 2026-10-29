import assert from "node:assert/strict";
import { test } from "node:test";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { HttpAgent } from "@ag-ui/client";
import type { BaseEvent, RunAgentInput } from "@ag-ui/core";
import { createAgUiHttpClient } from "../src/agui_http.js";

const run = "agui:" + "a".repeat(64);
function input(): RunAgentInput {
  return { protocolVersion: "1.0", threadId: "thread", runId: "native", messages: [{ id: "u", role: "user", content: "original user input" }], state: {}, tools: [], context: [], forwardedProps: {} };
}
const frames = [
  { type: "RUN_STARTED", threadId: "thread", runId: run },
  { type: "STATE_SNAPSHOT", snapshot: { count: 0 } },
  { type: "CUSTOM", name: "business.noop", value: {} },
  { type: "TEXT_MESSAGE_START", messageId: "a", role: "assistant" },
  { type: "TEXT_MESSAGE_CONTENT", messageId: "a", delta: "hello" },
  { type: "TEXT_MESSAGE_END", messageId: "a" },
  { type: "RUN_FINISHED", threadId: "thread", runId: run },
];
function deferred() { let resolve!: () => void; return { promise: new Promise<void>(r => resolve = r), resolve: () => resolve() }; }

for (const reliable of [false, true]) test(`actual HttpAgent HTTP canonical application and pacing (${reliable ? "reliable" : "standard"})`, async () => {
  const requests: unknown[] = [];
  const server = createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    requests.push(req.method === "POST" ? JSON.parse(Buffer.concat(chunks).toString()) : { method: req.method });
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    for (const [index, frame] of frames.entries()) {
      const text = JSON.stringify(frame);
      if (reliable && index === 4) {
        for (const [chunk_index, content] of [text.slice(0, 20), text.slice(20)].entries()) res.write(`id: v2p.chunk${chunk_index}\ndata: ${JSON.stringify({ type: "CUSTOM", name: "zebra.canonical_chunk", value: { chunk_index, content, last: chunk_index === 1 } })}\n\n`);
      } else res.write(`${reliable ? `id: v2p.event${index}\n` : ""}data: ${text}\n\n`);
    }
    res.end();
  });
  await new Promise<void>(r => server.listen(0, "127.0.0.1", r));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const gate = deferred(), entered = deferred();
  let seen = 0, reads = 0, admissions = 0;
  const cursors: (string | null)[] = [];
  const client = createAgUiHttpClient({ url: "/observe", reliable,
    admit: async (operation, candidate) => { admissions++; return { operation, input: { ...candidate, runId: run } }; },
    receipt: async () => { throw new Error("Unexpected admission reconciliation"); },
    fetch: async (url, init) => {
      const response = await fetch(origin + url, init);
      const reader = response.body!.getReader();
      return new Response(new ReadableStream({ async pull(controller) {
        reads++; const result = await reader.read(); if (result.done) controller.close(); else controller.enqueue(result.value);
      }, cancel() { return reader.cancel(); } }, { highWaterMark: 0 }), { headers: response.headers });
    },
    onEvent: async event => { seen++; if (event.type === "CUSTOM") { entered.resolve(); await gate.promise; } },
    onCursor: cursor => { cursors.push(cursor); },
  });
  try {
    await client.admit(input());
    const registered: BaseEvent[] = [];
    client.agent!.subscribe({ onEvent: ({event}) => { registered.push(event); } });
    let middlewareRuns = 0;
    client.agent!.use((input, next) => { middlewareRuns++; return next.run(input); });
    const completion = client.observe();
    await entered.promise;
    const readCount = reads;
    await new Promise(r => setTimeout(r, 30));
    assert.equal(seen, 3, "no-op callback must hold the actual HTTP parser");
    assert.equal(reads, readCount, "no body read while application is stalled");
    gate.resolve();
    const agent = await completion;
    assert.ok(agent instanceof HttpAgent);
    assert.equal(agent.messages[0]?.content, "original user input");
    assert.equal(agent.messages.at(-1)?.content, "hello");
    assert.equal(admissions, 1); assert.equal(requests.length, 1);
    if (reliable) assert.equal((requests[0] as {method:string}).method, "GET");
    else assert.equal((requests[0] as RunAgentInput).runId, run);
    assert.equal(registered.length, frames.length, "registered subscribers never see private barriers");
    assert.equal(seen, frames.length, "private application barriers never reach subscribers");
    if (reliable) assert.equal(cursors.at(-1), "v2p.event6");
    await assert.rejects(client.observe(), /exactly once/);
    // Runtime clones carry the actual URL/binding and get independent barrier state.
    const clone = agent.clone();
    assert.ok(clone instanceof HttpAgent); assert.notEqual(clone, agent); assert.equal(clone.url, agent.url);
    await clone.runAgent({ runId: run });
    assert.equal(requests.length, 2);
    assert.equal(registered.length, frames.length * 2); assert.equal(middlewareRuns, 2);
    assert.equal(admissions, 1);
  } finally { gate.resolve(); server.closeAllConnections(); await new Promise<void>(r => server.close(() => r())); }
});

test("unknown native admission reconciles the same captured operation without another POST", async () => {
  let admissions = 0, captured = "";
  const client = createAgUiHttpClient({ url: "/observe",
    admit: async operation => { admissions++; captured = operation; throw new Error("Unknown native outcome"); },
    receipt: async operation => { assert.equal(operation, captured); return { operation, input: { ...input(), runId: run } }; },
  });
  await assert.rejects(client.admit(input()), /Unknown/);
  await assert.rejects(client.admit(input()), /original admission/);
  await client.reconcile(); assert.equal(admissions, 1);
});

async function nativeFixture(events: unknown[], exercise: (fetchImpl: typeof fetch) => Promise<void>) {
  const server = createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    for (const [index, event] of events.entries()) res.write(`id: v2p.event${index}\ndata: ${JSON.stringify(event)}\n\n`);
    res.end();
  });
  await new Promise<void>(r => server.listen(0, "127.0.0.1", r));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try { await exercise((url, init) => fetch(origin + url, init)); }
  finally { server.closeAllConnections(); await new Promise<void>(r => server.close(() => r())); }
}
function admission() {
  return { admit: async (operation: string, candidate: RunAgentInput) => ({ operation, input: { ...candidate, runId: run } }),
    receipt: async () => { throw new Error("No admission reconciliation"); } };
}

test("official normalization precedes binding and known poisoned state patches never ACK", async () => {
  await nativeFixture([frames[0], { type: "CUSTOM", name: "business", value: {}, runId: "unknown-extra-field" }, frames[6]], async fetch => {
    const client = createAgUiHttpClient({ url: "/observe", fetch, ...admission() });
    await client.admit(input()); await client.observe();
  });
  await nativeFixture([frames[0], frames[1], { type: "STATE_DELTA", delta: [{ op: "remove", path: "/absent" }] }, frames[6]], async fetch => {
    const cursors: (string | null)[] = [];
    const client = createAgUiHttpClient({ url: "/observe", fetch, reliable: true, onCursor: value => { cursors.push(value); }, ...admission() });
    await client.admit(input()); await assert.rejects(client.observe(), /path|exist|resolve/i);
    assert.equal(cursors.at(-1), "v2p.event1");
    assert.deepEqual(client.agent!.state, { count: 0 });
  });
});

for (const callback of ["onEvent", "onStateChanged", "onMessagesChanged", "onTextMessageContentEvent"] as const) {
  test(`registered ${callback} failure is fatal without later application or ACK`, async () => {
    await nativeFixture(frames, async fetch => {
      const cursors: (string | null)[] = [], seen: string[] = [];
      const client = createAgUiHttpClient({ url: "/observe", fetch, reliable: true,
        onCursor: value => { cursors.push(value); }, onEvent: event => { seen.push(event.type); }, ...admission() });
      await client.admit(input());
      client.agent!.subscribe({ [callback]: async () => { throw new Error("registered callback failed"); } });
      await assert.rejects(client.observe(), /registered callback failed/);
      assert.ok(!seen.includes("RUN_FINISHED"));
      assert.notEqual(cursors.at(-1), "v2p.event6");
    });
  });
}

test("abort rejects a blocked real HTTP application and cancels its source", async () => {
  await nativeFixture(frames, async fetch => {
    const entered = deferred(), release = deferred(), controller = new AbortController();
    const client = createAgUiHttpClient({ url: "/observe", fetch,
      onEvent: async event => { if (event.type === "CUSTOM") { entered.resolve(); await release.promise; } }, ...admission() });
    await client.admit(input());
    const completion = client.observe(controller.signal);
    await entered.promise; controller.abort(new Error("explicit abort"));
    await assert.rejects(completion, /explicit abort/); release.resolve();
    assert.equal(client.agent!.messages.length, 1);
  });
});

test("reliable GET resumes a retained canonical prefix in the same official pipeline", async () => {
  let connections = 0, admissions = 0;
  const content = JSON.stringify(frames[4]), cut = 35;
  const server = createServer((req, res) => {
    assert.equal(req.method, "GET");
    connections++;
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    const write = (event: unknown, id: string) => res.write(`id: ${id}\ndata: ${JSON.stringify(event)}\n\n`);
    if (connections === 1) {
      assert.equal(req.headers["last-event-id"], undefined);
      for (const [index, frame] of frames.slice(0, 4).entries()) write(frame, `v2p.event${index}`);
      write({ type: "CUSTOM", name: "zebra.canonical_chunk", value: { chunk_index: 0, content: content.slice(0, cut), last: false } }, "v2p.partial");
    } else {
      assert.equal(connections, 2); assert.equal(req.headers["last-event-id"], "v2p.partial");
      write({ type: "CUSTOM", name: "zebra.canonical_chunk", value: { chunk_index: 1, content: content.slice(cut), last: true } }, "v2p.event4");
      write(frames[5], "v2p.event5"); write(frames[6], "v2p.event6");
      res.write(`data: ${JSON.stringify({ type: "CUSTOM", name: "zebra.stream.reset", value: { reason: "canonical_closed" } })}\n\n`);
    }
    res.end();
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const events: BaseEvent[] = [];
  const client = createAgUiHttpClient({ url: "/observe", reliable: true,
    ...admission(), admit: async (operation, candidate) => { admissions++; return { operation, input: { ...candidate, runId: run } }; },
    fetch: (url, init) => fetch(origin + url, init), onEvent: event => { events.push(event); },
  });
  try {
    await client.admit(input()); const actual = client.agent; const agent = await client.observe();
    assert.equal(agent, actual); assert.equal(connections, 2); assert.equal(admissions, 1);
    assert.equal(events.filter(event => event.type === "RUN_STARTED").length, 1);
    assert.equal(events.filter(event => event.type === "TEXT_MESSAGE_CONTENT").length, 1);
    assert.equal(agent.messages.at(-1)?.content, "hello"); assert.equal(client.cursor, "v2p.event6");
  } finally { server.closeAllConnections(); await new Promise<void>(r => server.close(() => r())); }
});

test("clean nonterminal standard EOF fails without resubmission or forgetting original operation", async () => {
  await nativeFixture(frames.slice(0, 3), async fetch => {
    let posts = 0;
    const client = createAgUiHttpClient({ url: "/observe", fetch, ...admission(),
      admit: async (operation, candidate) => { posts++; return { operation, input: { ...candidate, runId: run } }; } });
    await client.admit(input()); const original = client.pendingOperation;
    await assert.rejects(client.observe(), /before its terminal/);
    assert.equal(client.pendingOperation, original); assert.equal(posts, 1);
    await assert.rejects(client.observe(), /exactly once/);
  });
});

test("captured native protocol declaration defaults once and contradictory versions never admit", async () => {
  let posts = 0;
  const client = createAgUiHttpClient({ url: "/observe", ...admission(),
    admit: async (operation, candidate) => { posts++; assert.equal(candidate.protocolVersion, "1.0");
      // Python's field order differs; only JSON object order is irrelevant.
      return { operation, input: { state: candidate.state, messages: candidate.messages,
        context: candidate.context, tools: candidate.tools, forwardedProps: candidate.forwardedProps,
        threadId: candidate.threadId, runId: run, protocolVersion: "1.0" } }; } });
  await assert.rejects(client.admit({ ...input(), protocolVersion: "1.1" }), /protocol 1.0/);
  assert.equal(posts, 0);
  const {protocolVersion: _version, ...absent} = input();
  await client.admit(absent); assert.equal(posts, 1);
});


test("explicit prepared initial locator attaches only to a fresh client without native admission", async () => {
  await nativeFixture(frames, async fetch => {
    let writes = 0;
    const client = createAgUiHttpClient({ url:"/observe",fetch,
      admit: async () => { writes++; throw new Error("No initial readmission"); },
      receipt: async () => { throw new Error("Already prepared"); } });
    const prepared = {operation:globalThis.crypto.randomUUID(), input:{...input(),runId:run}};
    await client.attachPrepared(prepared); assert.equal(writes, 0);
    await assert.rejects(client.attachPrepared(prepared), /fresh client/);
    const agent = await client.observe(); assert.equal(agent.messages.at(-1)?.content,"hello");
    assert.equal(writes, 0);
    const unknown = createAgUiHttpClient({url:"/observe", ...admission(), admit:async () => { throw new Error("lost"); }});
    await assert.rejects(unknown.admit(input()), /lost/);
    await assert.rejects(unknown.attachPrepared(prepared), /fresh client/);
  });
});

test("large actual HTTP ingress waits for registered no-op and post-apply callbacks", async () => {
  const many = [...frames.slice(0,2), ...Array.from({length:3000},(_,index) => ({type:"CUSTOM",name:"business.noop",value:{index,text:"x".repeat(4096)}})),...frames.slice(3)];
  await nativeFixture(many, async fetchImpl => {
    const eventGate=deferred(), eventEntered=deferred(), appliedGate=deferred(), appliedEntered=deferred();
    let reads=0, held=false, appliedHeld=false;
    const seen:string[]=[];
    const client=createAgUiHttpClient({url:"/observe",...admission(),
      fetch:async (url,init) => {const response=await fetchImpl(url,init), reader=response.body!.getReader();
        return new Response(new ReadableStream({async pull(controller){reads++;const next=await reader.read();if(next.done)controller.close();else controller.enqueue(next.value);},cancel(){return reader.cancel();}},{highWaterMark:0}),{headers:response.headers});},
      onApplied:async agent => {if(!appliedHeld&&agent.messages.at(-1)?.content==="hello"){appliedHeld=true;appliedEntered.resolve();await appliedGate.promise;}},
    });
    await client.admit(input());
    client.agent!.subscribe({onEvent:async ({event})=>{seen.push(event.type);if(!held&&event.type==="CUSTOM"){held=true;eventEntered.resolve();await eventGate.promise;}}});
    const completion=client.observe();
    await eventEntered.promise;const atEvent=reads;
    await new Promise(r=>setTimeout(r,25));assert.equal(reads,atEvent);assert.equal(seen.length,3);
    eventGate.resolve();await appliedEntered.promise;const atApplied=reads;
    await new Promise(r=>setTimeout(r,25));assert.equal(reads,atApplied);assert.ok(!seen.includes("RUN_FINISHED"));
    appliedGate.resolve();await completion;assert.ok(reads>atEvent);assert.equal(seen.length,many.length);
  });
});

test("abort also rejects registered finalization without losing the original locator", async () => {
  await nativeFixture(frames,async fetch=>{
    const entered=deferred(),release=deferred(),abort=new AbortController();
    const client=createAgUiHttpClient({url:"/observe",fetch,...admission()});
    await client.admit(input());const original=client.pendingOperation;
    client.agent!.subscribe({onRunFinalized:async()=>{entered.resolve();await release.promise;}});
    const completion=client.observe(abort.signal);await entered.promise;abort.abort(new Error("finalization abort"));
    await assert.rejects(completion,/finalization abort/);assert.equal(client.pendingOperation,original);release.resolve();
  });
});

test("semantic input digest preserves literal prototype keys and rejects invalid JSON before admission", async()=>{
  const {canonicalDigest}=await import("../src/canonical_digest.js");
  assert.notEqual(await canonicalDigest(JSON.parse('{"__proto__":{"scope":"a"}}')),await canonicalDigest({}));
  let writes=0;
  const client=createAgUiHttpClient({url:"/observe",...admission(),admit:async()=>{writes++;throw new Error("must not admit");}});
  await assert.rejects(client.admit({...input(),state:{x:Infinity}}));
  await assert.rejects(client.admit({...input(),state:{x:1n}}));assert.equal(writes,0);
});

test("post-apply rejection holds the last signed cursor and never reconnects",async()=>{
  await nativeFixture(frames,async fetchImpl=>{
    let requests=0;
    const client=createAgUiHttpClient({url:"/observe",reliable:true,...admission(),
      fetch:(url,init)=>{requests++;return fetchImpl(url,init);},onApplied:async()=>{throw new Error("application ACK failed");}});
    await client.admit(input());await assert.rejects(client.observe(),/application ACK failed/);
    assert.equal(client.cursor,null);assert.equal(requests,1);assert.ok(client.pendingOperation);
  });
});

test("server native transport captures its validated origin and trusted coordinates",async()=>{
  const {createNativeAgUiTransport}=await import("../src/agui_native.js");
  const requests:{url:string;headers:Headers;body:unknown}[]=[];
  const options={origin:"https://native.example",publicPath:"/observe",taskId:"thread",internalRunId:"native",segmentId:"segment",
    expectedRevision:3,profile:"agui-standard-1.0" as const,headers:async()=>({Authorization:"Bearer fixture-auth"}),
    fetch:(async(url:unknown,init:RequestInit)=>{requests.push({url:String(url),headers:new Headers(init.headers),body:init.body?JSON.parse(String(init.body)):null});
      return Response.json({status:"prepared",input:{...input(),runId:run}});}) as typeof fetch};
  const native=createNativeAgUiTransport(options);
  options.origin="https://evil.invalid";options.taskId="other";options.segmentId="other";options.expectedRevision=77;
  await native.admit(globalThis.crypto.randomUUID(),input());
  await native.fetch("/observe",{method:"POST",body:JSON.stringify({...input(),runId:run})});
  assert.equal(requests.length,3);
  assert.ok(requests.every(request=>request.url.startsWith("https://native.example/agui/threads/thread/runs/native/")));
  assert.ok(requests.every(request=>request.headers.get("X-Zebra-Command-Segment")==="segment"));
  assert.equal((requests[0]?.body as {expectedRevision:number}).expectedRevision,3);
});

for (const reliable of [false, true]) test(`terminal with open HTTP body waits finalization and cursor then cleans reader (${reliable})`,async()=>{
  let closed=0,acks=0;
  const server=createServer((_req,res)=>{
    res.writeHead(200,{"Content-Type":"text/event-stream"});
    for(const [index,frame] of frames.entries()) res.write(`${reliable?`id: v2p.event${index}\n`:""}data: ${JSON.stringify(frame)}\n\n`);
    res.write(`id: v2p.after-terminal\ndata: ${JSON.stringify({type:"CUSTOM",name:"zebra.stream.reset",value:{}})}\n\n`);
    res.on("close",()=>{closed++;}); // Intentionally no EOF after terminal.
  });
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  const origin=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const entered=deferred(),release=deferred(),acked=deferred(),releaseAck=deferred();
  const client=createAgUiHttpClient({url:"/observe",reliable,...admission(),fetch:(url,init)=>fetch(origin+url,init),
    onCursor:async cursor=>{acks++;if(cursor==="v2p.event6"){acked.resolve();await releaseAck.promise;}}});
  try{
    await client.admit(input());
    client.agent!.subscribe({onRunFinalized:async()=>{entered.resolve();await release.promise;}});
    let finished=false;const completion=client.observe().then(()=>{finished=true;});
    await entered.promise;assert.equal(finished,false);assert.ok(client.pendingOperation);
    if(reliable) assert.equal(client.cursor,"v2p.event5");
    release.resolve();
    if(reliable){await acked.promise;assert.equal(finished,false);assert.equal(client.cursor,"v2p.event5");releaseAck.resolve();}
    await completion;
    for(let n=0;n<20&&closed===0;n++) await new Promise(r=>setTimeout(r,5));
    assert.equal(closed,1);assert.equal(acks,reliable?7:0);assert.equal(client.pendingOperation,undefined);
  }finally{server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));}
});

test("registered finalization failure never acknowledges terminal",async()=>{
  await nativeFixture(frames,async fetch=>{
    const client=createAgUiHttpClient({url:"/observe",fetch,reliable:true,...admission()});
    await client.admit(input());client.agent!.subscribe({onRunFinalized:async()=>{throw new Error("final hook failed");}});
    await assert.rejects(client.observe(),/final hook failed/);assert.equal(client.cursor,"v2p.event5");assert.ok(client.pendingOperation);
  });
});

test("reliable reset awaits cursor persistence and stays outside official business events",async()=>{
  await nativeFixture([frames[0],{type:"CUSTOM",name:"zebra.stream.reset",value:{}},...frames.slice(1)],async fetch=>{
    const cursors:(string|null)[]=[],seen:string[]=[];const entered=deferred(),release=deferred();
    const client=createAgUiHttpClient({url:"/observe",reliable:true,fetch,...admission(),
      onCursor:async cursor=>{if(cursor===null){entered.resolve();await release.promise;}cursors.push(cursor);},
      onEvent:event=>{seen.push(event.type);}});
    await client.admit(input());const completion=client.observe();await entered.promise;
    assert.deepEqual(seen,["RUN_STARTED"]);assert.equal(client.cursor,"v2p.event0");release.resolve();await completion;
    assert.equal(cursors[1],null);assert.equal(seen.length,frames.length);assert.equal(client.cursor,"v2p.event7");
  });
});

test("reliable reset clears a retained prefix; failed reset persistence stops before application",async()=>{
  const {readReliableAgUiStream}=await import("../src/sse_stream.js");
  const canonical=JSON.stringify(frames[0]);
  const values=[
    {type:"CUSTOM",name:"zebra.canonical_chunk",value:{chunk_index:0,content:canonical.slice(0,20),last:false}},
    {type:"CUSTOM",name:"zebra.stream.reset",value:{}},
    {type:"CUSTOM",name:"zebra.canonical_chunk",value:{chunk_index:0,content:canonical,last:true}},
    frames[6],
  ];
  const body=()=>new ReadableStream<Uint8Array>({start(controller){values.forEach((event,index)=>controller.enqueue(new TextEncoder().encode(`id: v2p.event${index}\ndata: ${JSON.stringify(event)}\n\n`)));controller.close();}});
  const recovery={active:true},seen:unknown[]=[],cursors:(string|null)[]=[];
  await readReliableAgUiStream(body(),{signal:new AbortController().signal,recovery,onCanonical:async event=>{seen.push(event);},onCursor:async cursor=>{cursors.push(cursor);}});
  assert.deepEqual(seen,[frames[0],frames[6]]);assert.deepEqual(cursors,["v2p.event0",null,"v2p.event2","v2p.event3"]);
  let applied=0;const failed:(string|null)[]=[];
  await assert.rejects(readReliableAgUiStream(body(),{signal:new AbortController().signal,recovery:{active:true},
    onCanonical:async()=>{applied++;},onCursor:async cursor=>{if(cursor===null)throw new Error("reset persist failed");failed.push(cursor);}}),/reset persist failed/);
  assert.equal(applied,0);assert.deepEqual(failed,["v2p.event0"]);
});
