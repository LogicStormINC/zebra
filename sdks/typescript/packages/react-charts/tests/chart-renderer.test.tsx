import assert from "node:assert/strict";
import { test } from "node:test";
import React, { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { AgentVegaLiteRenderer, validateVegaLiteSpec } from "../src/index.tsx";

const options = { maxInlineDataRows: 2, maxSpecBytes: 4_096, specVersion: "6" };

test("deeply nested JSON charts fail locally without removing sibling content", async () => {
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement });
  const { createRoot } = await import("react-dom/client");
  const container = dom.window.document.getElementById("root")!;
  const root = createRoot(container);
  const spec = JSON.parse('{"nested":'.repeat(10_000) + "null" + "}".repeat(10_000));
  try {
    for (const state of ["ready", "processing", "failed"] as const) {
      await act(async () => root.render(createElement("section", null,
        createElement("p", null, "Retained useful result"),
        createElement(AgentVegaLiteRenderer, {
          context: { allowedAppCapabilities: [], labels: { appFailed: "failed", appUnavailable: "unavailable", close: "close", download: "download", failed: "failed", loading: "loading", openImage: "open", unavailable: "unavailable", unsupported: "unsupported" } },
          message: { id: "message", role: "assistant", content: "", status: "complete" },
          part: { id: "deep-chart", type: "chart", state, specType: "vega-lite", specVersion: "6", title: "Example", description: "Example data", spec },
        }))));
      assert.equal(container.querySelector("p")?.textContent, "Retained useful result");
      assert.ok(container.querySelector(".zebra-agent-chart--fallback"));
    }
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
  }
});

test("failed chart fetches retry on request and network recovery without remounting", async () => {
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  const originalFetch = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => { requests += 1; throw new Error("offline"); };
  const { createRoot } = await import("react-dom/client");
  const container = dom.window.document.getElementById("root")!;
  const root = createRoot(container);
  try {
    await act(async () => root.render(createElement(AgentVegaLiteRenderer, {
      context: {
        allowedAppCapabilities: [],
        labels: { appFailed: "failed", appUnavailable: "unavailable", close: "close", download: "download", failed: "failed", loading: "loading", openImage: "open", unavailable: "unavailable", unsupported: "unsupported" },
        resolveArtifact: async (artifactId: string) => ({ artifactId, mimeType: "application/json", url: "https://host.example/spec" }),
      },
      message: { id: "message", role: "assistant", content: "", status: "complete" },
      part: { id: "chart", type: "chart", state: "ready", specType: "vega-lite", specVersion: "6", title: "Example", description: "Example data", specArtifactId: "spec" },
    })));
    assert.equal(requests, 1);
    const canvas = container.querySelector(".zebra-agent-chart__canvas");
    await act(async () => (container.querySelector("button") as HTMLButtonElement).click());
    assert.equal(requests, 2);
    assert.equal(container.querySelector(".zebra-agent-chart__canvas"), canvas);
    await act(async () => dom.window.dispatchEvent(new dom.window.Event("online")));
    assert.equal(requests, 3);
    let pendingSignal: AbortSignal | undefined;
    globalThis.fetch = async (_url, init) => {
      requests += 1;
      pendingSignal = init?.signal as AbortSignal;
      return new Promise<Response>((_resolve, reject) => {
        pendingSignal!.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      });
    };
    await act(async () => (container.querySelector("button") as HTMLButtonElement).click());
    assert.equal(requests, 4);
    assert.equal(pendingSignal?.aborted, false);
    await act(async () => root.unmount());
    assert.equal(pendingSignal?.aborted, true);
    dom.window.dispatchEvent(new dom.window.Event("online"));
    assert.equal(requests, 4);
  } finally {
    globalThis.fetch = originalFetch;
    dom.window.close();
  }
});

test("Vega-Lite guard accepts bounded declarative data", () => {
  assert.doesNotThrow(() => validateVegaLiteSpec({ mark: "bar", data: { values: [{ x: "A", y: 1 }] }, encoding: { x: { field: "x" }, y: { field: "y" } } }, options));
});

test("Vega-Lite guard rejects remote and executable content", () => {
  assert.throws(() => validateVegaLiteSpec({ data: { url: "https://evil.example/data.json" }, mark: "bar" }, options), /forbidden/);
  assert.throws(() => validateVegaLiteSpec({ transform: [{ calculate: "datum.secret", as: "x" }], mark: "bar" }, options), /forbidden/);
  assert.throws(() => validateVegaLiteSpec({ transform: [{ filter: "datum.x > 2" }], mark: "bar" }, options), /forbidden/);
  assert.throws(() => validateVegaLiteSpec({ axis: { labelExpr: "datum.label" }, mark: "bar" }, options), /forbidden/);
  assert.throws(() => validateVegaLiteSpec({ condition: { test: "datum.x > 1" }, mark: "bar" }, options), /forbidden/);
});

test("Vega-Lite guard rejects unsupported versions and excessive inline rows", () => {
  assert.throws(() => validateVegaLiteSpec({ mark: "bar" }, { ...options, specVersion: "5" }), /version/);
  assert.throws(() => validateVegaLiteSpec({ data: { values: [1, 2, 3] }, mark: "bar" }, options), /too_large/);
});

test("failed charts resolve image and table Artifact fallbacks", async () => {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: "https://host.example" });
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement });
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ columns: ["label"], rows: [["A"]] }), { headers: { "content-length": "40" } });
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(container);
  const part = { id: "chart", type: "chart" as const, state: "failed" as const, specType: "vega-lite" as const, specVersion: "6", title: "Revenue", description: "Monthly revenue", fallbackImageArtifactId: "image", fallbackTableArtifactId: "table" };
  await act(async () => root.render(createElement(AgentVegaLiteRenderer, {
    context: {
      allowedAppCapabilities: [],
      labels: { appFailed: "failed", appUnavailable: "unavailable", close: "close", download: "download", failed: "failed", loading: "loading", openImage: "open", unavailable: "unavailable", unsupported: "unsupported" },
      resolveArtifact: async (artifactId: string) => ({ artifactId, mimeType: artifactId === "image" ? "image/png" : "application/json", url: `https://host.example/${artifactId}` }),
    },
    message: { id: "message", role: "assistant", content: "", status: "complete" },
    part,
  })));
  await act(async () => undefined);
  assert.equal(container.querySelector("img")?.getAttribute("src"), "https://host.example/image");
  assert.match(container.querySelector("table")?.textContent ?? "", /A/);
  await act(async () => root.render(createElement(AgentVegaLiteRenderer, {
    context: {
      allowedAppCapabilities: [],
      labels: { appFailed: "failed", appUnavailable: "unavailable", close: "close", download: "download", failed: "failed", loading: "loading", openImage: "open", unavailable: "unavailable", unsupported: "unsupported" },
      resolveArtifact: () => { throw new Error("artifact_access_unavailable"); },
    },
    message: { id: "message", role: "assistant", content: "", status: "complete" },
    part,
  })));
  assert.equal(container.querySelector("img"), null);
  assert.match(container.textContent ?? "", /failed/);
  await act(async () => root.unmount());
  globalThis.fetch = originalFetch;
  dom.window.close();
});
