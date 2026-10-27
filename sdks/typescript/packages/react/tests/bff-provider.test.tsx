import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { z } from "zod";
import type { BffRuntimeClientConfig } from "@zebra-agent/contracts";
import { ZebraAgentProvider, useZebraAction, useZebraClientStatus } from "../src/index.ts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const session = "11111111-1111-4111-8111-111111111111";
function config(fetchImpl: typeof fetch, suffix = "one"): BffRuntimeClientConfig {
  return { mode: "bff", baseUrl: `/api/agent/surfaces/${suffix}`, clientSessionId: session,
    controller: false, fetchImpl };
}
function render(config: BffRuntimeClientConfig) {
  function Fixture() {
    useZebraAction("app.ui.item.open", { parameters: z.object({}), result: z.object({}), handler: () => ({}) });
    return createElement("output", { id: "status" }, useZebraClientStatus());
  }
  return createElement(StrictMode, null, createElement(ZebraAgentProvider, {
    config, frontendAppId: "fixture-web", profileRevision: 1, profileDigest: "c".repeat(64), children: createElement(Fixture),
  }));
}
function domRoot() {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: "https://business.example/" });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, Node: dom.window.Node, HTMLElement: dom.window.HTMLElement });
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
  return { dom, container, root: createRoot(container) };
}

test("Provider observes unavailable/recovered/stopped rather than start Promise success", async () => {
  const { dom, root, container } = domRoot();
  let code = 503;
  const cfg = config(async input => Response.json(String(input).endsWith("/effects") ? { effects: [] } : {},
    { status: String(input).endsWith("/effects") ? code : 200 }));
  try {
    await act(async () => { root.render(render(cfg)); await new Promise(resolve => setTimeout(resolve, 20)); });
    assert.equal(container.querySelector("#status")?.textContent, "unavailable");
    code = 200;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 1100)); });
    assert.equal(container.querySelector("#status")?.textContent, "ready");
    code = 401;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 1100)); });
    assert.equal(container.querySelector("#status")?.textContent, "stopped");
  } finally { await act(async () => { root.unmount(); await Promise.resolve(); }); dom.window.close(); }
});

test("changing config stops the old runtime even across Strict Mode cleanup generations", async () => {
  const { dom, root } = domRoot();
  const polls = new Map<string, number>();
  const fetchImpl: typeof fetch = async input => {
    const url = String(input);
    if (url.endsWith("/effects")) polls.set(url, (polls.get(url) ?? 0) + 1);
    return Response.json({ effects: [] });
  };
  try {
    await act(async () => { root.render(render(config(fetchImpl, "old"))); await new Promise(resolve => setTimeout(resolve, 20)); });
    await act(async () => { root.render(render(config(fetchImpl, "new"))); await new Promise(resolve => setTimeout(resolve, 20)); });
    const old = [...polls.keys()].find(url => url.includes("/old/"));
    assert.ok(old);
    const before = polls.get(old);
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 1100)); });
    assert.equal(polls.get(old), before, "old runtime continued polling after its config was replaced");
  } finally { await act(async () => { root.unmount(); await Promise.resolve(); }); dom.window.close(); }
});
