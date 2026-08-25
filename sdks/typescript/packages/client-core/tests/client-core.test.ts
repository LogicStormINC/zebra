import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ClientRuntimeError,
  MountedActionRegistry,
  ZebraClientRuntime,
  canonicalDigest,
  scrubResult,
} from "../src/index.ts";

const ACTION_DIGEST = "f".repeat(64);
const BINDING_DIGEST = "e".repeat(64);

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

test("same content yields the same canonical digest", async () => {
  assert.equal(
    await canonicalDigest({ b: 1, a: { d: 2, c: 3 } }),
    await canonicalDigest({ a: { c: 3, d: 2 }, b: 1 }),
  );
});

test("receipt results scrub sensitive fields", () => {
  const scrubbed = scrubResult({
    route: "/x",
    sessionToken: "abc",
    nested: { cookie: "sid" },
    rows: [{ value: 1, apiToken: "hidden" }],
  });
  assert.equal(scrubbed.route, "/x");
  assert.equal(scrubbed.sessionToken, "__redacted__");
  assert.equal((scrubbed.nested as Record<string, unknown>).cookie, "__redacted__");
  assert.deepEqual(scrubbed.rows, [{ value: 1, apiToken: "__redacted__" }]);
  const circular: Record<string, unknown> = {};
  circular.self = circular;
  assert.deepEqual(scrubResult(circular), { self: { error: "invalid_nested_result" } });
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
    controllerFenceToken: "controller-fence-value",
    taskId: "22222222-2222-4222-8222-222222222222",
    runId: "run-1",
    runBindingId: "33333333-3333-4333-8333-333333333333",
    clientBindingDigest: BINDING_DIGEST,
    actionContractDigests: { "app.ui.item.open": ACTION_DIGEST },
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
    expected_ui_revision: 0,
    expires_at: new Date().toISOString(),
    request_digest: "0".repeat(64),
    action_contract_digest: ACTION_DIGEST,
    client_binding_digest: BINDING_DIGEST,
  };
  await runtime.runEffect(effect);
  await runtime.runEffect(effect); // replay: no second execution
  const handlerCalls = calls.filter((entry) => entry === "handler");
  assert.equal(handlerCalls.length, 1);
});

test("session storage prevents effect replay after a page refresh", async () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  } as unknown as Storage;
  const config = {
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:session-secret-value",
    controllerFenceToken: "controller-fence-value",
    taskId: "22222222-2222-4222-8222-222222222222",
    runId: "run-1",
    runBindingId: "33333333-3333-4333-8333-333333333333",
    clientBindingDigest: BINDING_DIGEST,
    actionContractDigests: { "app.ui.item.open": ACTION_DIGEST },
    storage,
    fetchImpl: fakeFetch([]),
  };
  const effect = {
    effect_id: "refresh-effect",
    action_name: "app.ui.item.open",
    arguments: {},
    status: "pending" as const,
    expected_ui_revision: 0,
    expires_at: new Date().toISOString(),
    request_digest: "0".repeat(64),
    action_contract_digest: ACTION_DIGEST,
    client_binding_digest: BINDING_DIGEST,
  };
  let calls = 0;
  const first = ZebraClientRuntime.fromConfig(config);
  first.registry.mount(effect.action_name, () => {
    calls += 1;
    return {};
  });
  await first.runEffect(effect);
  const refreshed = ZebraClientRuntime.fromConfig(config);
  refreshed.registry.mount(effect.action_name, () => {
    calls += 1;
    return {};
  });
  await refreshed.runEffect(effect);
  assert.equal(calls, 1);
});

test("refresh during an in-flight handler never starts the effect twice", async () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  } as unknown as Storage;
  const config = {
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:session-secret-value",
    controllerFenceToken: "controller-fence-value",
    taskId: "22222222-2222-4222-8222-222222222222",
    runId: "run-1",
    runBindingId: "33333333-3333-4333-8333-333333333333",
    clientBindingDigest: BINDING_DIGEST,
    actionContractDigests: { "app.ui.item.open": ACTION_DIGEST },
    storage,
    fetchImpl: fakeFetch([]),
  };
  const effect = {
    effect_id: "inflight-refresh-effect",
    action_name: "app.ui.item.open",
    arguments: {},
    status: "pending" as const,
    expected_ui_revision: 0,
    expires_at: new Date().toISOString(),
    request_digest: "0".repeat(64),
    action_contract_digest: ACTION_DIGEST,
    client_binding_digest: BINDING_DIGEST,
  };
  let calls = 0;
  let finish!: () => void;
  const first = ZebraClientRuntime.fromConfig(config);
  first.registry.mount(effect.action_name, async () => {
    calls += 1;
    await new Promise<void>((resolve) => { finish = resolve; });
    return {};
  });
  const pending = first.runEffect(effect);
  await Promise.resolve();

  const refreshed = ZebraClientRuntime.fromConfig(config);
  refreshed.registry.mount(effect.action_name, () => {
    calls += 1;
    return {};
  });
  await refreshed.runEffect(effect);
  assert.equal(calls, 1);

  finish();
  await pending;
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
    controllerFenceToken: "controller-fence-value",
    taskId: "22222222-2222-4222-8222-222222222222",
    runId: "run-1",
    runBindingId: "33333333-3333-4333-8333-333333333333",
    clientBindingDigest: BINDING_DIGEST,
    actionContractDigests: { "app.ui.never": ACTION_DIGEST },
    fetchImpl,
  });
  await runtime.runEffect({
    effect_id: "e-2",
    action_name: "app.ui.never",
    arguments: {},
    status: "pending",
    expected_ui_revision: 0,
    expires_at: new Date().toISOString(),
    request_digest: "0".repeat(64),
    action_contract_digest: ACTION_DIGEST,
    client_binding_digest: BINDING_DIGEST,
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
    request_digest: "0".repeat(64),
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
    profileRevision: 2,
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

test("one React commit coalesces capability mounts", async () => {
  const bodies: Array<Record<string, unknown>> = [];
  const runtime = ZebraClientRuntime.fromConfig({
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:session-secret-value",
    fetchImpl: (async (_input: unknown, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return new Response("{}");
    }) as unknown as typeof fetch,
  });
  const base = {
    frontendAppId: "app-web",
    profileRevision: 2,
    profileDigest: "a".repeat(64),
    mountedReadables: [] as string[],
  };
  void runtime.scheduleMount({ ...base, mountedActions: ["app.first"] });
  await runtime.scheduleMount({
    ...base,
    mountedActions: ["app.first", "app.second"],
  });
  assert.equal(bodies.length, 1);
  assert.deepEqual(bodies[0]?.mounted_actions, ["app.first", "app.second"]);
  assert.equal(bodies[0]?.profile_revision, 2);
});

test("observer and stale-ui effects never invoke a handler", async () => {
  let observerCalls = 0;
  const observer = ZebraClientRuntime.fromConfig({
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:session-secret-value",
    fetchImpl: fakeFetch([]),
  });
  observer.registry.mount("app.open", () => {
    observerCalls += 1;
    return {};
  });
  const effect = {
    effect_id: "observer-effect",
    action_name: "app.open",
    arguments: {},
    status: "pending" as const,
    expected_ui_revision: 0,
    expires_at: new Date().toISOString(),
    request_digest: "a".repeat(64),
    action_contract_digest: ACTION_DIGEST,
    client_binding_digest: BINDING_DIGEST,
  };
  await observer.runEffect(effect);
  assert.equal(observerCalls, 0);

  const receipts: Array<Record<string, unknown>> = [];
  const controller = ZebraClientRuntime.fromConfig({
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:session-secret-value",
    controllerFenceToken: "controller-fence-value",
    taskId: "22222222-2222-4222-8222-222222222222",
    runId: "run-1",
    runBindingId: "33333333-3333-4333-8333-333333333333",
    clientBindingDigest: BINDING_DIGEST,
    actionContractDigests: { "app.open": ACTION_DIGEST },
    fetchImpl: (async (_input: unknown, init?: RequestInit) => {
      receipts.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return new Response("{}");
    }) as unknown as typeof fetch,
  });
  controller.registry.mount("app.open", () => {
    observerCalls += 1;
    return {};
  });
  await controller.runEffect({ ...effect, effect_id: "stale-effect", expected_ui_revision: 1 });
  assert.equal(observerCalls, 0);
  assert.equal(receipts[0]?.status, "stale_ui_state");
});

test("SSE reconnect sends Last-Event-ID and executes only client effects", async () => {
  let streamCalls = 0;
  let handlerCalls = 0;
  let secondHeaders: HeadersInit | undefined;
  let resolveSecond!: () => void;
  const secondStream = new Promise<void>((resolve) => {
    resolveSecond = resolve;
  });
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/effects")) {
      return new Response('{"effects":[]}');
    }
    if (url.endsWith("/stream")) {
      streamCalls += 1;
      if (streamCalls === 2) {
        secondHeaders = init?.headers;
        resolveSecond();
        return new Response(": keepalive\n\n");
      }
      const effect = {
        effect_id: "sse-effect-1",
        action_name: "app.ui.item.open",
        arguments: {},
        status: "pending",
        expected_ui_revision: 0,
        expires_at: new Date(Date.now() + 60_000).toISOString(),
        request_digest: "a".repeat(64),
        action_contract_digest: ACTION_DIGEST,
        client_binding_digest: BINDING_DIGEST,
        execution_location: "client",
      };
      return new Response(
        `id: cursor-1\ndata: ${JSON.stringify({ type: "STATE_DELTA", delta: [{ op: "add", value: effect }] })}\n\n`,
      );
    }
    return new Response("{}");
  }) as unknown as typeof fetch;
  const runtime = ZebraClientRuntime.fromConfig({
    baseUrl: "https://bff.example",
    clientSessionId: "11111111-1111-4111-8111-111111111111",
    sessionCredential: "11111111-1111-4111-8111-111111111111:session-secret-value",
    controllerFenceToken: "controller-fence-value",
    taskId: "22222222-2222-4222-8222-222222222222",
    runId: "run-1",
    runBindingId: "33333333-3333-4333-8333-333333333333",
    clientBindingDigest: BINDING_DIGEST,
    actionContractDigests: { "app.ui.item.open": ACTION_DIGEST },
    streamUrl: "https://bff.example/agui/threads/task/runs/run/stream",
    fetchImpl,
  });
  runtime.registry.mount("app.ui.item.open", () => {
    handlerCalls += 1;
    return { opened: true };
  });

  await runtime.start();
  await secondStream;
  runtime.stop();

  assert.equal(handlerCalls, 1);
  assert.equal(
    (secondHeaders as Record<string, string>)["Last-Event-ID"],
    "cursor-1",
  );
});
