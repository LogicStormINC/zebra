// Real owned native children/sockets; protocol fixture success is NOT live authority proof.
import assert from "node:assert/strict";
import net from "node:net";
import test from "node:test";
import { openGuardRpc, runNativeCheck } from "./browser_guard_rpc.mjs";

const program = (body) => ["--input-type=module", "-e",
  `import readline from 'node:readline'; import fs from 'node:fs';
  for await(const line of readline.createInterface({input:process.stdin})) {
    const request=JSON.parse(line); const reply=JSON.stringify({request_id:request.request_id,status:'passed'})+'\\n';
    ${body}
  }`];
const gone = (pid) => assert.throws(() => process.kill(pid, 0), { code: "ESRCH" });

test("one persistent child handles split UTF8 replies and fresh ordered calls", async () => {
  const windows = [];
  const rpc = openGuardRpc({ python: process.execPath, windows,
    args: program("process.stdout.write(reply.slice(0,7)); await new Promise(setImmediate); process.stdout.write(reply.slice(7));") });
  const pid = rpc.pid;
  try {
    await rpc.check("first"); await rpc.check("second");
    assert.equal(rpc.pid, pid); assert.equal(windows.length, 2);
    assert.ok(windows.every((row) => row.status === "passed" && row.queued_at_ms <= row.started_at_ms
      && row.started_at_ms <= row.ended_at_ms && row.duration_ms >= 0));
    assert.ok(windows[0].ended_at_ms <= windows[1].started_at_ms);
  } finally { await rpc.close(); }
  gone(pid);
});

for (const suffix of ["duplicate", "wrong_id", "partial_garbage", "blank"]) {
  test(`passed line plus ${suffix} in one native write never authorizes`, async () => {
    const extra = suffix === "duplicate" ? "reply" : suffix === "wrong_id"
      ? "JSON.stringify({request_id:'wrong',status:'passed'})+'\\n'" : JSON.stringify(suffix === "blank" ? "\n" : "garbage");
    const windows = [];
    const rpc = openGuardRpc({ python: process.execPath, windows,
      args: program(`fs.writeSync(1,reply+(${extra}));`) });
    try {
      await assert.rejects(rpc.check("mutation"), /guard_protocol_invalid/);
      assert.equal(windows[0].status, "failed"); assert.equal(windows[0].child_closed, true);
      await assert.rejects(rpc.check("later"), /guard_protocol_invalid/);
      gone(rpc.pid);
    } finally { await rpc.close(); }
  });
}

test("passed first request never caches authority for a denied second request", async () => {
  const rpc = openGuardRpc({ python: process.execPath, args: program(
    "globalThis.calls=(globalThis.calls??0)+1; process.stdout.write(globalThis.calls===1?reply:JSON.stringify({request_id:request.request_id,status:'denied'})+'\\n');") });
  try { await rpc.check("first"); await assert.rejects(rpc.check("second"), /guard_denied/); gone(rpc.pid); }
  finally { await rpc.close(); }
});

async function socketFixture() {
  let connected, timer;
  const accepted = new Promise((resolve, reject) => {
    connected = resolve;
    timer = setTimeout(() => reject(new Error("fixture_connect_deadline")), 5000);
  });
  const sockets = [];
  const server = net.createServer((socket) => { clearTimeout(timer); sockets.push(socket); connected(socket); });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return { port: server.address().port, accepted, async close() {
    clearTimeout(timer);
    for (const socket of sockets) socket.destroy();
    await new Promise((resolve) => server.close(resolve));
  } };
}

test("queue deadline includes waiting and kills/reaps child with its actual open socket", async () => {
  const fixture = await socketFixture(), windows = [];
  const rpc = openGuardRpc({ python: process.execPath, windows, args: program(
    `process.on('SIGTERM',()=>{}); const net=await import('node:net'); net.connect(${fixture.port},'127.0.0.1'); await new Promise(()=>{});`) });
  const first = rpc.check("first", { timeoutMs: 2000 }); first.catch(() => {});
  try {
    const socket = await fixture.accepted;
    const socketClosed = new Promise((resolve) => socket.once("close", resolve)); socket.resume();
    await assert.rejects(rpc.check("queued", { timeoutMs: 40 }), /guard_deadline/);
    await assert.rejects(first, /guard_deadline/);
    await socketClosed; gone(rpc.pid);
    assert.equal(windows[1].started_at_ms, null); assert.equal(windows[1].child_closed, true);
    assert.ok(windows[1].duration_ms >= 40);
  } finally { await rpc.close(); await fixture.close(); }
});

test("abort while waiting joins native child before rejection", async () => {
  const fixture = await socketFixture(), controller = new AbortController();
  const rpc = openGuardRpc({ python: process.execPath, args: program(
    `const net=await import('node:net'); net.connect(${fixture.port},'127.0.0.1'); await new Promise(()=>{});`) });
  const pending = rpc.check("cancel", { signal: controller.signal }); pending.catch(() => {});
  try {
    const socket = await fixture.accepted;
    const closed = new Promise((resolve) => socket.once("close", resolve)); socket.resume();
    controller.abort(); await assert.rejects(pending, /guard_cancelled/);
    await closed; gone(rpc.pid);
  } finally { await rpc.close(); await fixture.close(); }
});

test("overlong native output is bounded before accumulation and reports actual close", async () => {
  const windows = [];
  await assert.rejects(runNativeCheck({ python: process.execPath, args: ["-e", "process.stdout.write('x'.repeat(65536));setInterval(()=>{},1000)"],
    maxBytes: 1024, windows }), /native_child_output_limit/);
  assert.equal(windows[0].child_closed, true); assert.equal(windows[0].status, "failed");
});

test("native await leaves Node event loop runnable and preserves UTF8 output", async () => {
  let ticked = false;
  const pending = runNativeCheck({ python: process.execPath,
    args: ["-e", "process.stdout.write('图🙂');setImmediate(()=>process.stdout.write('终'))"] });
  await new Promise((resolve) => setImmediate(() => { ticked = true; resolve(); }));
  assert.equal(ticked, true); assert.equal(await pending, "图🙂终");
});

test("PID fallback also kills real descendants holding the pipe/socket after leader exit", async () => {
  const fixture = await socketFixture(); let descendant;
  const code = `const net=require('node:net');process.on('SIGTERM',()=>{});
    const socket=net.connect(${fixture.port},'127.0.0.1',()=>socket.write(String(process.pid)));setInterval(()=>{},1000);`;
  const pending = runNativeCheck({ python: process.execPath, timeoutMs: 300,
    args: ["-e", `require('node:child_process').spawn(process.execPath,['-e',${JSON.stringify(code)}],{stdio:['ignore',1,2]});process.stdout.write('parent');setTimeout(()=>process.exit(0),20);`] });
  pending.catch(() => {});
  try {
    const socket = await fixture.accepted;
    descendant = await new Promise((resolve) => socket.once("data", (data) => resolve(Number(data.toString()))));
    const closed = new Promise((resolve) => socket.once("close", resolve)); socket.resume();
    await assert.rejects(pending, /native_child_deadline/); await closed;
    // Give the native OS reaper bounded event-loop turns; a zombie is not final cleanup proof.
    for (let polls = 0; polls < 32; polls += 1) {
      try { process.kill(descendant, 0); }
      catch (error) { assert.equal(error.code, "ESRCH"); return; }
      await runNativeCheck({ python: "/bin/ps", args: ["-o", "stat=", "-p", String(descendant)] }).catch(() => {});
    }
    gone(descendant);
  } finally {
    if (descendant) { try { process.kill(descendant, "SIGKILL"); } catch {} }
    await fixture.close();
  }
});
