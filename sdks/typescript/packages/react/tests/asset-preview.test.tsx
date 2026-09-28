import assert from "node:assert/strict";
import { test } from "node:test";
import React, { act, createElement } from "react";
import { JSDOM } from "jsdom";

import { AgentAssetPreview, type AgentAssetPreviewProps } from "../src/index.ts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

async function mount(overrides: Partial<AgentAssetPreviewProps>) {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: "https://host.example" });
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
  Object.assign(globalThis, {
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    Node: dom.window.Node,
    window: dom.window,
  });
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(container);
  const props: AgentAssetPreviewProps = {
    asset: { artifactId: "artifact-1", fileName: "notes.md", mimeType: "text/markdown" },
    loadText: async () => "# Verified",
    renderMarkdown: (content) => createElement("article", { "data-markdown": true }, content),
    resolveArtifact: async (artifactId) => ({ artifactId, mimeType: "text/markdown", url: "/preview" }),
    ...overrides,
  };
  await act(async () => root.render(createElement(AgentAssetPreview, props)));
  await act(async () => undefined);
  return { container, dom, root };
}

test("delegates Markdown rendering to the host", async () => {
  const mounted = await mount({});
  assert.equal(mounted.container.querySelector("[data-markdown]")?.textContent, "# Verified");
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("renders bounded CSV rows as a table", async () => {
  const mounted = await mount({
    asset: { artifactId: "artifact-1", fileName: "metrics.csv", mimeType: "text/csv" },
    loadText: async () => "name,value\nalpha,42",
  });
  assert.equal(mounted.container.querySelector("th")?.textContent, "name");
  assert.equal(mounted.container.querySelector("td")?.textContent, "alpha");
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("keeps HTML preview disabled unless the host opts in", async () => {
  const mounted = await mount({
    asset: { artifactId: "artifact-1", fileName: "page.html", mimeType: "text/html" },
    loadText: async () => "<script>alert(1)</script>",
  });
  assert.equal(mounted.container.querySelector("iframe"), null);
  assert.match(mounted.container.textContent ?? "", /disabled by the host/i);
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});
