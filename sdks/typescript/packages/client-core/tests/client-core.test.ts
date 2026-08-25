import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ClientRuntimeError,
  MountedActionRegistry,
  ZebraClientRuntime,
  canonicalDigest,
  scrubResult,
} from "../src/index.ts";

test("registry resolves handlers by name only", async () => {
  const registry = new MountedActionRegistry();
  registry.mount("app.ui.item.open", () => ({ opened: true }));
  assert.deepEqual(await registry.dispatch("app.ui.item.open", {}), {
    opened: true,
  });
  await assert.rejects(
    () => registry.dispatch("app.ui.absent", {}),
    (error: unknown) =>
      error instanceof ClientRuntimeError && error.code === "action_not_mounted",
  );
});

test("same content yields the same canonical digest", () => {
  assert.equal(
    canonicalDigest({ b: 1, a: { d: 2, c: 3 } }),
    canonicalDigest({ a: { c: 3, d: 2 }, b: 1 }),
  );
});

test("receipt results scrub sensitive fields", () => {
  const scrubbed = scrubResult({
    route: "/x",
    sessionToken: "abc",
    nested: { cookie: "sid" },
  });
  assert.equal(scrubbed.route, "/x");
  assert.equal(scrubbed.sessionToken, "__redacted__");
  assert.equal((scrubbed.nested as Record<string, unknown>).cookie, "__redacted__");
});

function fakeFetch(log: string[], ok = true): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    log.push(String(input));
    return new Response(ok ? "{}" : '{"error":"x"}', {
      status: ok ? 200 : 500,
    });
  }) as unknown as typeof fetch;
}

test("runtime executes each effect at most once", async () => {
  const calls: string[] = [];
  const runtime = ZebraClientRuntime.fromConfig({
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:fence-token-value",
    fetchImpl: fakeFetch(calls),
  });
  runtime.registry.mount("app.ui.item.open", () => {
    calls.push("handler");
    return { opened: true };
  });
  const effect = {
    effect_id: "e-1",
    action_name: "app.ui.item.open",
    arguments: {},
    status: "pending" as const,
    expected_ui_revision: 1,
    expires_at: new Date().toISOString(),
    request_digest: "0".repeat(64),
  };
  await runtime.runEffect(effect);
  await runtime.runEffect(effect); // replay: no second execution
  const handlerCalls = calls.filter((entry) => entry === "handler");
  assert.equal(handlerCalls.length, 1);
});

test("unmounted actions return unavailable receipts", async () => {
  const receipts: unknown[] = [];
  const fetchImpl = (async (_input: unknown, init?: RequestInit) => {
    receipts.push(JSON.parse(String(init?.body)));
    return new Response("{}", { status: 200 });
  }) as unknown as typeof fetch;
  const runtime = ZebraClientRuntime.fromConfig({
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:fence-token-value",
    fetchImpl,
  });
  await runtime.runEffect({
    effect_id: "e-2",
    action_name: "app.ui.never",
    arguments: {},
    status: "pending",
    expected_ui_revision: 1,
    expires_at: new Date().toISOString(),
    request_digest: "0".repeat(64),
  });
  assert.equal((receipts[0] as { status: string }).status, "unavailable");
});

test("stale fence receipt rejection stops the runtime", async () => {
  let calls = 0;
  const fetchImpl = (async () => {
    calls += 1;
    return new Response("{}", { status: 409 });
  }) as unknown as typeof fetch;
  const runtime = ZebraClientRuntime.fromConfig({
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:fence-token-value",
    fetchImpl,
  });
  const accepted = await runtime.submitReceipt({
    effect_id: "e-3",
    status: "succeeded",
    result: {},
  });
  assert.equal(accepted, false);
  assert.equal(runtime.isStopped, true);
});

test("profile digest mismatch stops mounting", async () => {
  const runtime = ZebraClientRuntime.fromConfig({
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:fence-token-value",
    fetchImpl: fakeFetch([]),
  });
  const mount = {
    frontendAppId: "app-web",
    profileDigest: "a".repeat(64),
    mountedActions: ["app.ui.item.open"],
  };
  await runtime.mount(mount);
  await assert.rejects(
    () =>
      runtime.mount({ ...mount, profileDigest: "b".repeat(64) }),
    (error: unknown) =>
      error instanceof ClientRuntimeError &&
      error.code === "profile_digest_mismatch",
  );
});
