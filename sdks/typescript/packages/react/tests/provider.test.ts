/**
 * Import-level smoke test: the React package parses and exposes the
 * documented hook surface without a DOM renderer. Full Strict-Mode /
 * unmount / multi-tab behaviors need a DOM runner (jsdom + vitest) and
 * are registered as the SDK follow-up (CLIENT-REACT-HOOKS-01).
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { z } from "zod";

import {
  ZebraAgentProvider,
  useZebraAction,
  useZebraAgentState,
  useZebraClientStatus,
  useZebraReadable,
  useZebraTask,
} from "../src/index.ts";
import {
  ZebraHitlProvider,
  useZebraApproval,
  useZebraClarification,
} from "../src/hitl/index.ts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

test("react package exposes the ADR-CLIENT-01 hook surface", () => {
  assert.equal(typeof ZebraAgentProvider, "function");
  assert.equal(typeof useZebraReadable, "function");
  assert.equal(typeof useZebraAction, "function");
  assert.equal(typeof useZebraClientStatus, "function");
  assert.equal(typeof useZebraTask, "function");
  assert.equal(typeof useZebraAgentState, "function");
  assert.equal(typeof ZebraHitlProvider, "function");
  assert.equal(typeof useZebraApproval, "function");
  assert.equal(typeof useZebraClarification, "function");
});

test("Strict Mode coalesces action mount and provider releases the controller", async () => {
  const requests: Array<{ url: string; body: Record<string, unknown> }> = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    requests.push({
      url,
      body: init?.body === undefined
        ? {}
        : JSON.parse(String(init.body)) as Record<string, unknown>,
    });
    if (url.endsWith("/effects")) return new Response('{"effects":[]}');
    return new Response("{}");
  }) as unknown as typeof fetch;
  function ActionFixture() {
    useZebraAction("app.ui.item.open", {
      parameters: z.object({ itemId: z.string() }),
      result: z.object({ opened: z.boolean() }),
      handler: ({ itemId }) => ({ opened: itemId.length > 0 }),
    });
    return null;
  }
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  const container = dom.window.document.getElementById("root");
  assert.ok(container !== null);
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
  });
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(
        StrictMode,
        null,
        createElement(
          ZebraAgentProvider,
          {
            config: {
              baseUrl: "https://bff.example",
              clientSessionId: "11111111-1111-4111-8111-111111111111",
              sessionCredential:
                "11111111-1111-4111-8111-111111111111:session-secret-value",
              controllerFenceToken: "controller-fence-value",
              taskId: "22222222-2222-4222-8222-222222222222",
              runId: "run-1",
              runBindingId: "33333333-3333-4333-8333-333333333333",
              clientBindingDigest: "b".repeat(64),
              actionContractDigests: { "app.ui.item.open": "a".repeat(64) },
              fetchImpl,
            },
            frontendAppId: "fixture-web",
            profileRevision: 2,
            profileDigest: "c".repeat(64),
            children: createElement(ActionFixture),
          },
        ),
      ),
    );
  });
  const mounts = requests.filter((request) => request.url.endsWith("/mount"));
  assert.ok(mounts.length >= 1);
  assert.deepEqual(mounts.at(-1)?.body.mounted_actions, ["app.ui.item.open"]);

  await act(async () => {
    root.unmount();
    await Promise.resolve();
  });

  assert.equal(requests.filter((request) => request.url.endsWith("/release")).length, 1);
  dom.window.close();
});

test("Zod rejects invalid action parameters before the handler runs", async () => {
  let handlerCalls = 0;
  let resolveReceipt!: (body: Record<string, unknown>) => void;
  const receipt = new Promise<Record<string, unknown>>((resolve) => {
    resolveReceipt = resolve;
  });
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/effects")) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      return new Response(JSON.stringify({ effects: [{
        effect_id: "invalid-args",
        action_name: "app.ui.item.open",
        arguments: { itemId: 42 },
        status: "pending",
        expected_ui_revision: 1,
        expires_at: new Date(Date.now() + 60_000).toISOString(),
        request_digest: "d".repeat(64),
        action_contract_digest: "a".repeat(64),
        client_binding_digest: "b".repeat(64),
      }] }));
    }
    if (url.endsWith("/receipts")) {
      resolveReceipt(JSON.parse(String(init?.body)) as Record<string, unknown>);
    }
    return new Response("{}");
  }) as unknown as typeof fetch;
  function InvalidArgsFixture() {
    useZebraAction("app.ui.item.open", {
      parameters: z.object({ itemId: z.string() }),
      result: z.object({ opened: z.boolean() }),
      handler: () => {
        handlerCalls += 1;
        return { opened: true };
      },
    });
    return null;
  }
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  const container = dom.window.document.getElementById("root");
  assert.ok(container !== null);
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
  });
  const root = createRoot(container);
  await act(async () => {
    root.render(createElement(ZebraAgentProvider, {
      config: {
        baseUrl: "https://bff.example",
        clientSessionId: "11111111-1111-4111-8111-111111111111",
        sessionCredential:
          "11111111-1111-4111-8111-111111111111:session-secret-value",
        controllerFenceToken: "controller-fence-value",
        taskId: "22222222-2222-4222-8222-222222222222",
        runId: "run-1",
        runBindingId: "33333333-3333-4333-8333-333333333333",
        clientBindingDigest: "b".repeat(64),
        actionContractDigests: { "app.ui.item.open": "a".repeat(64) },
        fetchImpl,
      },
      frontendAppId: "fixture-web",
      profileRevision: 2,
      profileDigest: "c".repeat(64),
      children: createElement(InvalidArgsFixture),
    }));
  });
  let submitted: Record<string, unknown> = {};
  await act(async () => {
    submitted = await receipt;
  });
  assert.equal(handlerCalls, 0);
  assert.equal(submitted.status, "failed");
  assert.deepEqual(submitted.result, { error: "client_action_failed" });
  await act(async () => {
    root.unmount();
    await Promise.resolve();
  });
  dom.window.close();
});
