import assert from "node:assert/strict";
import { test } from "node:test";
import React, { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { AgentVegaLiteRenderer, validateVegaLiteSpec } from "../src/index.tsx";

const options = { maxInlineDataRows: 2, maxSpecBytes: 4_096, specVersion: "6" };

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
  await act(async () => root.unmount());
  globalThis.fetch = originalFetch;
  dom.window.close();
});
