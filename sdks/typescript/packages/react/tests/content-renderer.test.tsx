import assert from "node:assert/strict";
import { test } from "node:test";
import React, { act, createElement } from "react";
import { JSDOM } from "jsdom";

import { AgentContentRenderer, type AgentContentRendererProps } from "../src/index.ts";
import type { AgentExternalVideoPart, AgentMessage } from "@zebra-agent/ui-contracts";

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
        { id: "video", type: "video", state: "ready", artifactId: "video-1", captionsArtifactId: "captions-1", captionsLanguage: "zh-CN", mimeType: "video/mp4", title: "Demo" },
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
  assert.equal(video?.querySelector("track")?.getAttribute("srclang"), "zh-CN");
  assert.equal(download?.getAttribute("href"), "https://media.example/file-1");
  assert.ok(resolved.includes("image-thumb-1:preview"));
  assert.ok(!resolved.includes("image-1:preview"));
  assert.ok(resolved.includes("video-1:preview"));
  assert.ok(resolved.includes("captions-1:captions"));
  assert.ok(resolved.includes("file-1:download"));
  await act(async () => {
    mounted.container.querySelector<HTMLButtonElement>(".zebra-agent-media__image-button")?.click();
  });
  assert.ok(resolved.includes("image-1:preview"));
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("image dialog reports full-size failures and restores focus", async () => {
  const mounted = await mount({
    message: message({
      content: "",
      parts: [{ id: "image", type: "image", state: "ready", artifactId: "full", thumbnailArtifactId: "thumb", mimeType: "image/png", alt: "Evidence" }],
    }),
    resolveArtifact: async (artifactId) => {
      if (artifactId === "full") throw new Error("expired");
      return { artifactId, mimeType: "image/png", url: `https://media.example/${artifactId}` };
    },
  });
  await act(async () => undefined);
  const trigger = mounted.container.querySelector<HTMLButtonElement>(".zebra-agent-media__image-button");
  assert.ok(trigger);
  await act(async () => trigger.click());
  await act(async () => undefined);
  const close = mounted.container.querySelector<HTMLButtonElement>(".zebra-agent-media-dialog__close");
  assert.equal(mounted.dom.window.document.activeElement, close);
  assert.match(mounted.container.querySelector('[role="alert"]')?.textContent ?? "", /failed/i);
  await act(async () => close?.click());
  assert.equal(mounted.dom.window.document.activeElement, trigger);
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("known external video hosts embed only after a click and retain an external link", async () => {
  const cases: { provider: AgentExternalVideoPart["provider"]; url: string; embed: string; href: string }[] = [
    { provider: "youtube", url: "https://youtu.be/AbCdEfGhI12?t=20", embed: "https://www.youtube-nocookie.com/embed/AbCdEfGhI12", href: "https://www.youtube.com/watch?v=AbCdEfGhI12" },
    { provider: "vimeo", url: "https://vimeo.com/123456?autoplay=1", embed: "https://player.vimeo.com/video/123456", href: "https://vimeo.com/123456" },
    { provider: "bilibili", url: "https://www.bilibili.com/video/BV1xx411c7mD?p=2", embed: "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD", href: "https://www.bilibili.com/video/BV1xx411c7mD" },
  ];
  for (const item of cases) {
    const mounted = await mount({ labels: { playExternalVideo: "播放视频" }, message: message({ parts: [{ id: "external", type: "external-video", state: "ready", title: "Demo", posterUrl: "https://images.example/poster.jpg", provider: item.provider, url: item.url }] }) });
    assert.equal(mounted.container.querySelector("iframe"), null);
    assert.equal(mounted.container.querySelector(".zebra-agent-media__external-fallback button")?.textContent, "播放视频");
    assert.equal(mounted.container.querySelector(".zebra-agent-media__external-fallback img")?.getAttribute("src"), "https://images.example/poster.jpg");
    assert.equal(mounted.container.querySelector(".zebra-agent-media__external-fallback img")?.getAttribute("referrerpolicy"), "no-referrer");
    assert.equal(mounted.container.querySelector("figcaption a")?.getAttribute("href"), item.href);
    assert.equal(mounted.container.querySelector("figcaption a")?.getAttribute("rel"), "noopener noreferrer");
    await act(async () => mounted.container.querySelector<HTMLButtonElement>("button")?.click());
    assert.equal(mounted.container.querySelector("iframe")?.getAttribute("src"), item.embed);
    assert.equal(mounted.container.querySelector("iframe")?.getAttribute("sandbox"), "allow-scripts allow-same-origin allow-presentation");
    await act(async () => mounted.root.unmount());
    mounted.dom.window.close();
  }
});

test("external video hides a rejected poster and keeps a playable title and source link", async () => {
  const mounted = await mount({ message: message({ parts: [{
    id: "external", type: "external-video", state: "ready", title: "Latest video",
    posterUrl: "https://i1.hdslb.com/bfs/archive/poster.jpg", provider: "bilibili",
    url: "https://www.bilibili.com/video/BV1xx411c7mD",
  }] }) });
  const poster = mounted.container.querySelector(".zebra-agent-media__external-fallback img");
  assert.ok(poster);
  await act(async () => poster.dispatchEvent(new mounted.dom.window.Event("error", { bubbles: true })));
  assert.equal(mounted.container.querySelector(".zebra-agent-media__external-fallback img"), null);
  assert.match(mounted.container.querySelector(".zebra-agent-media__external-title")?.textContent ?? "", /Latest video/);
  assert.ok(mounted.container.querySelector(".zebra-agent-media__external-fallback button"));
  assert.equal(mounted.container.querySelector("figcaption a")?.getAttribute("href"), "https://www.bilibili.com/video/BV1xx411c7mD");
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("direct mp4/webm use native video and a link without Artifact resolution", async () => {
  for (const extension of ["mp4", "webm"] as const) {
    let resolved = false;
    const url = `https://media.example/movie.${extension}?token=abc`;
    const mounted = await mount({
      message: message({ parts: [{ id: "external", type: "external-video", state: "ready", title: "Movie", provider: "direct", url, posterUrl: "https://media.example/poster.jpg" }] }),
      resolveArtifact: () => { resolved = true; throw new Error("unexpected Artifact lookup"); },
    });
    assert.equal(mounted.container.querySelector("video source")?.getAttribute("src"), url);
    assert.equal(mounted.container.querySelector("video source")?.getAttribute("type"), `video/${extension}`);
    assert.equal(mounted.container.querySelector("video")?.getAttribute("poster"), "https://media.example/poster.jpg");
    assert.equal(mounted.container.querySelector("figcaption a")?.getAttribute("href"), url);
    assert.equal(resolved, false);
    await act(async () => mounted.container.querySelector("video")?.dispatchEvent(new mounted.dom.window.Event("error")));
    assert.equal(mounted.container.querySelector("video"), null);
    assert.equal(mounted.container.querySelector(".zebra-agent-media__external-fallback img")?.getAttribute("src"), "https://media.example/poster.jpg");
    assert.equal(mounted.container.querySelector("figcaption a")?.getAttribute("href"), url);
    await act(async () => mounted.root.unmount());
    mounted.dom.window.close();
  }
});

test("unrecognized video websites retain a source link without unsafe iframe embedding", async () => {
  const mounted = await mount({ message: message({ content: "", parts: [{
    id: "website-video", type: "external-video", state: "ready", provider: "website",
    url: "https://videos.example.com/watch/123", title: "Video",
  }] }) });
  assert.equal(mounted.container.querySelector("iframe"), null);
  assert.equal(mounted.container.querySelector("a")?.getAttribute("href"), "https://videos.example.com/watch/123");
  await act(async () => mounted.root.unmount());
  mounted.dom.window.close();
});

test("external video rejects unsafe and mismatched URLs; failed media keeps a safe poster/link", async () => {
  const rejected: { provider: AgentExternalVideoPart["provider"]; url: string }[] = [
    { provider: "youtube", url: "javascript:alert(1)" },
    { provider: "youtube", url: "https://www.youtube.com.evil.example/watch?v=AbCdEfGhI12" },
    { provider: "youtube", url: "https://user:pass@www.youtube.com/watch?v=AbCdEfGhI12" },
    { provider: "vimeo", url: "https://vimeo.com.evil.example/123456" },
    { provider: "bilibili", url: "https://www.bilibili.com/video/not-an-id" },
    { provider: "direct", url: "http://media.example/movie.mp4" },
    { provider: "direct", url: "https://127.0.0.1/movie.mp4" },
    { provider: "direct", url: "https://media.example/movie.svg" },
  ];
  for (const item of rejected) {
    const mounted = await mount({ message: message({ parts: [{ id: "external", type: "external-video", state: "ready", title: "Unsafe", provider: item.provider, url: item.url }] }) });
    assert.equal(mounted.container.querySelector("iframe, video, a"), null, item.url);
    assert.match(mounted.container.textContent ?? "", /cannot be played/i);
    await act(async () => mounted.root.unmount());
    mounted.dom.window.close();
  }
  const mounted = await mount({ message: message({ parts: [{ id: "external", type: "external-video", state: "failed", title: "Unavailable", provider: "vimeo", url: "https://vimeo.com/123456", posterUrl: "javascript:alert(1)" }] }) });
  assert.equal(mounted.container.querySelector("iframe, video, img"), null);
  assert.equal(mounted.container.querySelector("figcaption a")?.getAttribute("href"), "https://vimeo.com/123456");
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
