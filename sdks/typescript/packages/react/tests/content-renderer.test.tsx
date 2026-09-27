import assert from "node:assert/strict";
import { test } from "node:test";
import React, { act, createElement } from "react";
import { JSDOM } from "jsdom";

import { AgentContentRenderer, type AgentContentRendererProps } from "../src/index.ts";
import type { AgentMessage } from "@zebra-agent/ui-contracts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

async function mount(props: AgentContentRendererProps) {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: "https://host.example" });
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    Event: dom.window.Event,
    KeyboardEvent: dom.window.KeyboardEvent,
    MessageEvent: dom.window.MessageEvent,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
  });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(container);
  await act(async () => root.render(createElement(AgentContentRenderer, props)));
  return { container, dom, root };
}

function message(overrides: Partial<AgentMessage> = {}): AgentMessage {
  return { id: "message-1", role: "assistant", content: "legacy text", status: "complete", ...overrides };
}

test("legacy string messages render through the typed content surface", async () => {
  const mounted = await mount({ message: message() });
  assert.match(mounted.container.textContent ?? "", /legacy text/);
  assert.equal(mounted.container.querySelectorAll(".zebra-agent-content__text").length, 1);
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("image, video and file parts resolve opaque Artifact ids", async () => {
  const resolved: string[] = [];
  const mounted = await mount({
    message: message({
      content: "",
      parts: [
        { id: "image", type: "image", state: "ready", artifactId: "image-1", thumbnailArtifactId: "image-thumb-1", mimeType: "image/png", alt: "Build chart", width: 640, height: 360 },
        { id: "video", type: "video", state: "ready", artifactId: "video-1", mimeType: "video/mp4", title: "Demo" },
        { id: "file", type: "file", state: "ready", artifactId: "file-1", mimeType: "text/csv", name: "result.csv" },
      ],
    }),
    resolveArtifact: async (artifactId, purpose) => {
      resolved.push(`${artifactId}:${purpose}`);
      return { artifactId, mimeType: artifactId === "video-1" ? "video/mp4" : "application/octet-stream", url: `https://media.example/${artifactId}` };
    },
  });
  await act(async () => undefined);
  const image = mounted.container.querySelector("img");
  const video = mounted.container.querySelector("video");
  const download = mounted.container.querySelector('a[download="result.csv"]');
  assert.equal(image?.getAttribute("alt"), "Build chart");
  assert.equal(video?.querySelector("source")?.getAttribute("type"), "video/mp4");
  assert.equal(video?.getAttribute("preload"), "metadata");
  assert.equal(download?.getAttribute("href"), "https://media.example/file-1");
  assert.ok(resolved.includes("image-thumb-1:preview"));
  assert.ok(!resolved.includes("image-1:preview"));
  assert.ok(resolved.includes("video-1:preview"));
  assert.ok(resolved.includes("file-1:download"));
  await act(async () => {
    mounted.container.querySelector<HTMLButtonElement>(".zebra-agent-media__image-button")?.click();
  });
  assert.ok(resolved.includes("image-1:preview"));
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("renderer registry handles optional chart packages without changing the base bundle", async () => {
  const mounted = await mount({
    message: message({
      content: "",
      parts: [{ id: "chart", type: "chart", state: "ready", specType: "vega-lite", specVersion: "5", title: "Revenue", description: "Monthly revenue", spec: { mark: "bar" } }],
    }),
    renderers: {
      chart: ({ part }) => createElement("section", { "data-chart": part.id }, "Vega-Lite chart"),
    },
  });
  assert.equal(mounted.container.querySelector('[data-chart="chart"]')?.textContent, "Vega-Lite chart");
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("MCP App resources fail closed on origin or capability drift", async () => {
  const mounted = await mount({
    allowedAppCapabilities: ["chart.read"],
    message: message({
      content: "",
      parts: [{ id: "app", type: "app", state: "ready", resourceUri: "ui://chart/one", title: "Interactive chart", requestedCapabilities: ["chart.read"] }],
    }),
    resolveAppResource: async () => ({
      allowedOrigin: "https://trusted.example",
      capabilities: [],
      resourceUri: "ui://chart/one",
      url: "https://evil.example/app",
      version: "2025-11-21",
    }),
  });
  await act(async () => undefined);
  assert.equal(mounted.container.querySelector("iframe"), null);
  assert.match(mounted.container.textContent ?? "", /failed to load/i);
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("MCP App host accepts only messages from the resolved frame and origin", async () => {
  const messages: string[] = [];
  const mounted = await mount({
    allowedAppCapabilities: ["chart.read"],
    message: message({
      content: "",
      parts: [{ id: "app", type: "app", state: "ready", resourceUri: "ui://chart/one", title: "Interactive chart", requestedCapabilities: ["chart.read"] }],
    }),
    onAppMessage: (value) => messages.push(value.method),
    resolveAppResource: async () => ({
      allowedOrigin: "https://trusted.example",
      capabilities: ["chart.read"],
      resourceUri: "ui://chart/one",
      url: "https://trusted.example/app",
      version: "2025-11-21",
    }),
  });
  await act(async () => undefined);
  const frame = mounted.container.querySelector("iframe");
  assert.ok(frame?.contentWindow);
  const payload = { id: "message-1", method: "chart.select", version: "2025-11-21" };
  mounted.dom.window.dispatchEvent(new mounted.dom.window.MessageEvent("message", {
    data: payload,
    origin: "https://evil.example",
    source: frame.contentWindow,
  }));
  mounted.dom.window.dispatchEvent(new mounted.dom.window.MessageEvent("message", {
    data: payload,
    origin: "https://trusted.example",
    source: frame.contentWindow,
  }));
  assert.deepEqual(messages, ["chart.select"]);
  assert.equal(frame.getAttribute("sandbox"), "allow-forms allow-scripts");
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});
