import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement, StrictMode, useEffect } from "react";
import { JSDOM } from "jsdom";

import { AgentChat, AgentConversationTimeline, type AgentPartRendererProps } from "../src/index.ts";
import { selectConversationItems } from "../src/components/conversation-items.ts";
import { AgentConversationAnnouncement } from "../src/components/conversation-announcement.tsx";
import type { AgentConversationItem, AgentConversationTurn, AgentMessage } from "@zebra-agent/ui-contracts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

test("terminal Turns never replay a live Working status", () => {
  for (const status of ["completed", "failed", "partial", "blocked", "cancelled"] as const) {
    const value = turn(status);
    value.items = [{ id: "checking", kind: "status", state: { phase: "running", safeMessage: "Checking", availableActions: [] } }];
    assert.equal(selectConversationItems(value).some(item => item.kind === "status"), false);
  }
});

test("answer delivery folds work while allowing manual reopening", async () => {
  const { container, dom, root } = await mount();
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [turn("running")], collapseWork: false })));
  assert.equal(container.querySelector("details")?.open, true);
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [turn("running")], collapseWork: true })));
  assert.equal(container.querySelector("details")?.open, false);
  await act(async () => container.querySelector("summary")?.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })));
  assert.equal(container.querySelector("details")?.open, true);
  await act(async () => root.unmount()); dom.window.close();
});

test("completed tools do not imply the running turn completed", async () => {
  const { container, dom, root } = await mount();
  const value = turn("running");
  value.workSegments = value.workSegments.map(segment => ({
    ...segment, activities: segment.activities.map(item => ({ ...item, status: "completed" as const })),
  }));
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [value] })));
  assert.match(container.querySelector("summary")?.textContent ?? "", /Running/);
  await act(async () => root.unmount());
  dom.window.close();
});

test("public evidence messages and tools fold together without folding answer media", async () => {
  const { container, dom, root } = await mount();
  const value = turn("running");
  value.items = [
    { id: "evidence", kind: "message", message: { id: "evidence", role: "assistant", content: "已核对订阅历史", status: "complete" } },
    { id: "tool", kind: "activity", segment: value.workSegments[0]! },
  ];
  const render = (collapseWork: boolean) => act(async () => root.render(createElement(AgentConversationTimeline,
    { turns: [value], collapseWork, workMessageIds: ["evidence"] })));
  await render(false);
  const group = container.querySelector<HTMLDetailsElement>(".zebra-agent-turn__progress")!;
  assert.equal(group.open, true);
  assert.match(group.textContent!, /已核对订阅历史/);
  assert.equal(group.textContent!.includes("Repository inspected"), false);
  await render(true);
  assert.equal(group.open, false);
  assert.equal(container.querySelectorAll(".zebra-agent-turn__progress").length, 1);
  await act(async () => {
    const toggled = new Promise<Event>(resolve => group.addEventListener("toggle", resolve, { once: true }));
    group.querySelector("summary")!.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    await toggled;
  });
  assert.equal(group.open, true);
  value.status = "completed";
  await render(true);
  assert.equal(group.open, false);
  await act(async () => root.unmount()); dom.window.close();
});

async function mount() {
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    Event: dom.window.Event,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
  });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  const { createRoot } = await import("react-dom/client");
  return { container, dom, root: createRoot(container) };
}

function turn(status: AgentConversationTurn["status"]): AgentConversationTurn {
  return {
    id: "turn-1",
    status,
    userMessage: { id: "user-1", role: "user", content: "Inspect repository", status: "complete" },
    workSegments: [{
      id: "work-1",
      label: "Execution · 2",
      activities: [
        { activityId: "read", kind: "tool", status: status === "running" ? "running" : "completed", title: "Read files" },
        { activityId: "test", kind: "tool", status: status === "failed" ? "failed" : "completed", title: "Run tests" },
      ],
    }],
    assistantMessage: { id: "assistant-1", role: "assistant", content: "Repository inspected", status: "complete" },
  };
}

test("Turn timeline preserves prompt, work and answer order", async () => {
  const { container, dom, root } = await mount();
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [turn("running")] })));
  const text = container.textContent ?? "";
  assert.ok(text.indexOf("Inspect repository") < text.indexOf("Read files"));
  assert.ok(text.indexOf("Read files") < text.indexOf("Repository inspected"));
  assert.equal((container.querySelector("details") as HTMLDetailsElement).open, true);
  assert.equal(container.querySelector('[data-live-turn="true"]') !== null, true);
  assert.equal(container.querySelector(".zebra-agent-turn__rail"), null);
  assert.equal(container.querySelector('[data-activity-kind="tool"]') !== null, true);
  await act(async () => root.unmount());
  dom.window.close();
});

test("work summaries expose ZCode-style inline hierarchy and duration", async () => {
  const { container, dom, root } = await mount();
  const base = turn("completed");
  const value: AgentConversationTurn = {
    ...base,
    workSegments: [{
      ...base.workSegments[0]!,
      activities: [{ ...base.workSegments[0]!.activities[0]!, durationMs: 1_240 }, ...base.workSegments[0]!.activities.slice(1)],
    }],
  };
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [value] })));
  const summary = container.querySelector(".zebra-agent-activity summary");
  assert.ok(summary);
  assert.equal(summary.closest("details")?.classList.contains("zebra-agent-activity--terminal"), true);
  assert.match(summary.textContent ?? "", /Execution · 2.*Completed/);
  const firstActivity = container.querySelector(".zebra-agent-activity__item");
  assert.match(firstActivity?.textContent ?? "", /1\.2s · Completed/);
  await act(async () => root.unmount());
  dom.window.close();
});

test("successful work collapses while failed work remains open", async () => {
  const { container, dom, root } = await mount();
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [turn("running")] })));
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [turn("completed")] })));
  assert.equal((container.querySelector("details") as HTMLDetailsElement).open, false);

  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [turn("running")] })));
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [turn("failed")] })));
  assert.equal((container.querySelector("details") as HTMLDetailsElement).open, true);
  assert.match(container.textContent ?? "", /Failed/);
  await act(async () => root.unmount());
  dom.window.close();
});

test("partial delivery stays distinct and failed tools remain visible after later success", async () => {
  const { container, dom, root } = await mount();
  const base = turn("running");
  const render = async (status: AgentConversationTurn["status"], withWork = true) => {
    await act(async () => root.render(createElement(AgentConversationTimeline, {
      activityLabels: {
        partial: "部分完成",
        failed: "失败",
        failedActivities: (count) => `${count} 项失败`,
      },
      runStatusLabels: { outcomes: { partial: "部分结果", failed: "运行失败" } },
      turns: [{
        ...base,
        status,
        workSegments: withWork ? [{
          id: "work-1",
          activities: [
            { activityId: "search", kind: "tool", title: "Search", status: "failed" },
            { activityId: "read", kind: "tool", title: "Read", status: status === "running" ? "running" : "completed" },
          ],
        }] : [],
      }],
    })));
  };
  await render("running");
  assert.match(container.querySelector("summary [role=status]")?.textContent ?? "", /Running · 1 项失败/);
  assert.doesNotMatch(container.textContent ?? "", /Retrying/);
  await render("partial");
  assert.match(container.querySelector("summary")?.textContent ?? "", /部分完成 · 1 项失败/);
  assert.equal(container.querySelector("details")?.open, true);
  assert.match(container.querySelector(".zebra-agent-run-status [role=status]")?.textContent ?? "", /部分结果/);
  assert.match(container.textContent ?? "", /Repository inspected/);
  await render("completed");
  assert.match(container.querySelector("summary")?.textContent ?? "", /Completed · 1 项失败/);
  assert.equal(container.querySelector("details")?.open, true);
  await render("partial", false);
  assert.match(container.querySelector("[role=status]")?.textContent ?? "", /部分结果/);
  await render("failed", false);
  assert.match(container.querySelector("[role=status]")?.textContent ?? "", /运行失败/);
  assert.match(container.textContent ?? "", /Repository inspected/);
  await act(async () => root.unmount());
  dom.window.close();
});

function message(id: string, content: string, status: AgentMessage["status"] = "complete"): AgentMessage {
  return { id, role: "assistant", content, status };
}

async function settleAnnouncements() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

test("ordered items interleave public messages, execution, status and partial results before completion", async () => {
  const { container, dom, root } = await mount();
  const { assistantMessage: _answer, ...base } = turn("running");
  const items: readonly AgentConversationItem[] = [
    { id: "partial", sequence: 4, kind: "message", message: message("partial-result", "First result", "streaming") },
    { id: "wait", sequence: 3, kind: "status", state: { phase: "running", safeMessage: "Reading the next source", availableActions: [] } },
    { id: "work", sequence: 2, kind: "activity", segment: { ...base.workSegments[0]!, label: "" } },
    { id: "comment", sequence: 1, kind: "message", message: message("commentary", "Checking sources") },
    { id: "tail-1", kind: "message", message: message("tail-1", "Unsequenced first") },
    { id: "tail-2", kind: "message", message: message("tail-2", "Unsequenced second") },
  ];
  const original = JSON.stringify(items);
  const value = { ...base, items };
  assert.deepEqual(selectConversationItems(value).map((item) => item.id), ["comment", "work", "wait", "partial", "tail-1", "tail-2"]);
  assert.equal(JSON.stringify(items), original);
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [value] })));
  const text = container.textContent ?? "";
  const expected = ["Inspect repository", "Checking sources", "Read files", "Reading the next source", "First result", "Unsequenced first", "Unsequenced second"];
  for (let index = 1; index < expected.length; index += 1) {
    assert.ok(text.indexOf(expected[index - 1]!) < text.indexOf(expected[index]!));
  }
  assert.match(container.querySelector("summary")?.textContent ?? "", /Execution process/);
  assert.equal(container.querySelectorAll("details").length, 1);
  assert.equal(container.querySelector('[data-live-turn="true"]') !== null, true);
  assert.doesNotMatch(text, /Repository inspected|Thinking/i);
  await act(async () => root.unmount());
  dom.window.close();
});

test("replay selects the latest revision while final confirmation keeps the first slot and stable identity", async () => {
  const { container, dom, root } = await mount();
  const base = turn("completed");
  const provisional = message("selected", "Draft", "streaming");
  const value: AgentConversationTurn = {
    ...base,
    assistantMessage: message("selected", "Confirmed"),
    items: [
      { id: "original", sequence: 1, kind: "message", message: provisional },
      { id: "original", sequence: 9, kind: "message", message: { ...provisional, content: "Revision" } },
      { id: "other", sequence: 2, kind: "message", message: message("other", "Other result") },
      { id: "final-replay", sequence: 10, kind: "message", message: { ...provisional, content: "Later revision" } },
      { id: "prompt-replay", kind: "message", message: base.userMessage! },
    ],
  };
  const original = JSON.stringify(value);
  const selected = selectConversationItems(value);
  assert.deepEqual(selected.map((item) => [item.id, item.sequence]), [["original", 1], ["other", 2]]);
  assert.equal(selected[0]?.kind === "message" && selected[0].message.content, "Confirmed");
  assert.equal(JSON.stringify(value), original);
  await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [value] })));
  assert.deepEqual([...container.querySelectorAll(".zebra-agent-message__content")].map((element) => element.textContent), ["Inspect repository", "Confirmed", "Other result"]);
  assert.equal(container.querySelector("details"), null);
  await act(async () => root.unmount());
  dom.window.close();
});

test("unsequenced replay and equal sequences preserve input order, and a distinct final answer is appended", () => {
  const value: AgentConversationTurn = {
    ...turn("completed"),
    items: [
      { id: "unsequenced", kind: "message", message: message("unsequenced", "First") },
      { id: "equal-1", sequence: 1, kind: "message", message: message("equal-1", "One") },
      { id: "equal-2", sequence: 1, kind: "message", message: message("equal-2", "Two") },
      { id: "unsequenced", sequence: 10, kind: "message", message: message("unsequenced", "Revised") },
    ],
  };
  const selected = selectConversationItems(value);
  assert.deepEqual(selected.map((item) => item.id), ["equal-1", "equal-2", "unsequenced", "assistant-1"]);
  assert.equal(selected[2]?.sequence, undefined);
  assert.equal(selected[2]?.kind === "message" && selected[2].message.content, "Revised");
  assert.deepEqual(selectConversationItems({ ...value, items: [] }).map((item) => item.id), ["assistant-1"]);
});

test("activity/status replay updates existing slots and explicit final parts can remove provisional content", () => {
  const base = turn("completed");
  const provisional: AgentMessage = { ...base.assistantMessage!, parts: [{ id: "part", type: "text", state: "ready", format: "plain", text: "Draft" }] };
  const items: readonly AgentConversationItem[] = [
    { id: "work", kind: "activity", segment: base.workSegments[0]! },
    { id: "state", kind: "status", state: { phase: "running", availableActions: [] } },
    { id: "output", kind: "message", message: provisional },
    { id: "work", kind: "activity", segment: { id: "work-1", activities: [] } },
    { id: "state", kind: "status", state: { phase: "terminal", outcome: "completed", availableActions: [] } },
  ];
  const selected = selectConversationItems({ ...base, items, assistantMessage: { ...base.assistantMessage!, parts: [] } });
  assert.deepEqual(selected.map((item) => item.id), ["work", "state", "output"]);
  assert.equal(selected[0]?.kind === "activity" && selected[0].segment.activities.length, 0);
  assert.equal(selected[1]?.kind === "status" && selected[1].state.phase, "terminal");
  assert.deepEqual(selected[2]?.kind === "message" && selected[2].message.parts, []);
});

test("streaming revisions, reorder, replay and final confirmation preserve image, video, iframe and chart nodes", async () => {
  const { container, dom, root } = await mount();
  let chartMounts = 0;
  let chartUnmounts = 0;
  let resolutions = 0;
  const Chart = ({ part }: AgentPartRendererProps) => {
    useEffect(() => { chartMounts += 1; return () => { chartUnmounts += 1; }; }, []);
    return createElement("div", { "data-chart-id": part.id }, "Rendered chart");
  };
  const contentRenderer = {
    renderers: { chart: Chart },
    resolveArtifact: async (artifactId: string) => {
      resolutions += 1;
      return { artifactId, mimeType: "application/octet-stream", url: `https://media.example/${artifactId}` };
    },
  };
  const media: AgentMessage = {
    ...message("media-message", "Partial result", "streaming"),
    parts: [
      { id: "text", type: "text", state: "ready", format: "plain", text: "Partial result" },
      { id: "image", type: "image", state: "ready", artifactId: "image", mimeType: "image/png", alt: "Evidence" },
      { id: "video", type: "video", state: "ready", artifactId: "video", mimeType: "video/mp4", title: "Recording" },
      { id: "online", type: "external-video", state: "ready", provider: "bilibili", url: "https://www.bilibili.com/video/BV1xx411c7mD", title: "Online recording" },
      { id: "chart", type: "chart", state: "ready", specType: "vega-lite", specVersion: "v5", spec: { mark: "bar" }, title: "Chart", description: "Values" },
    ],
  };
  const base: AgentConversationTurn = { id: "media-turn", status: "running", workSegments: [] };
  const render = async (value: AgentConversationTurn) => {
    await act(async () => root.render(createElement(AgentConversationTimeline, { contentRenderer, turns: [value] })));
  };
  await render({ ...base, items: [{ id: "output", sequence: 2, kind: "message", message: media }] });
  await act(async () => container.querySelector<HTMLButtonElement>(".zebra-agent-media__external-fallback button")?.click());
  const selectors = ["img", "video", "iframe", "[data-chart-id]"];
  const nodes = selectors.map((selector) => container.querySelector(selector));
  assert.ok(nodes.every(Boolean));
  const video = container.querySelector("video")!;
  video.currentTime = 12;
  const revised: AgentMessage = {
    ...media,
    parts: media.parts!.map((part) => part.type === "text" ? { ...part, text: "Revised result" } : { ...part }),
  };
  const items: readonly AgentConversationItem[] = [
    { id: "earlier", sequence: 1, kind: "message", message: message("earlier", "Earlier commentary") },
    { id: "output", sequence: 2, kind: "message", message: revised },
  ];
  await render({ ...base, items });
  const final = message(media.id, "Revised result");
  await render({ ...base, status: "completed", items: [...items, { id: "confirmation", sequence: 3, kind: "message", message: final }], assistantMessage: final });
  await render({ ...base, status: "completed", items: [{ id: "snapshot-output", sequence: 2, kind: "message", message: revised }, items[0]!], assistantMessage: final });
  selectors.forEach((selector, index) => assert.equal(container.querySelector(selector), nodes[index]));
  assert.equal(video.currentTime, 12);
  assert.equal(chartMounts, 1);
  assert.equal(chartUnmounts, 0);
  assert.equal(resolutions, 2);
  assert.equal(container.querySelectorAll("video").length, 1);
  assert.equal(container.querySelectorAll("iframe").length, 1);
  const confirmed = selectConversationItems({ ...base, items, assistantMessage: final })[1];
  assert.equal(confirmed?.kind === "message" && confirmed.message.parts, revised.parts);
  await settleAnnouncements();
  const announcements = [...container.querySelectorAll(".zebra-agent-turn__announcement")];
  assert.ok(announcements.some((element) => element.textContent?.includes("Revised result\nEvidence\nRecording")));
  await act(async () => root.unmount());
  assert.equal(chartUnmounts, 1);
  dom.window.close();
});

test("announcements wait for complete messages and explicit terminal status is not duplicated", async () => {
  const { container, dom, root } = await mount();
  const output = message("progress", "Checking", "streaming");
  const base: AgentConversationTurn = { id: "turn", status: "running", workSegments: [] };
  const render = async (current: AgentMessage, terminal = false) => {
    await act(async () => root.render(createElement(AgentConversationTimeline, {
      turns: [{ ...base, status: terminal ? "partial" : "running", items: [
        { id: "public", kind: "message", message: current },
        { id: "state", kind: "status", state: terminal
          ? { phase: "terminal", outcome: "partial", safeMessage: "One source was unavailable", availableActions: [] }
          : { phase: "running", availableActions: [] } },
      ] }],
    })));
  };
  await render(output);
  const announcement = container.querySelector(".zebra-agent-turn__announcement");
  assert.equal(announcement?.textContent, "");
  await render({ ...output, content: "Checking another source" });
  assert.equal(announcement?.textContent, "");
  await render({ ...output, content: "Checked available sources", status: "complete" }, true);
  await settleAnnouncements();
  assert.equal(container.querySelector(".zebra-agent-turn__announcement"), announcement);
  assert.equal(announcement?.textContent, "Checked available sources");
  assert.equal(announcement?.getAttribute("aria-atomic"), "true");
  assert.equal(announcement?.getAttribute("aria-live"), "polite");
  assert.equal(container.querySelectorAll(".zebra-agent-run-status").length, 1);
  assert.match(container.querySelector(".zebra-agent-run-status [role=status]")?.textContent ?? "", /Partially completed.*One source was unavailable/);
  await act(async () => root.unmount());
  dom.window.close();
});

test("split confirmation and corrected final preserve the qualifier layout and same video", async () => {
  const { container, dom, root } = await mount();
  const provisional: AgentMessage = {
    ...message("answer", "Draft", "streaming"),
    parts: [
      { id: "answer-text", type: "text", state: "ready", format: "plain", text: "Draft" },
      { id: "answer-video", type: "video", state: "ready", artifactId: "video", mimeType: "video/mp4", title: "Evidence recording" },
      { id: "qualifier", type: "text", state: "ready", format: "plain", text: "Illustrative only; not live verification" },
    ],
  };
  const base: AgentConversationTurn = {
    id: "corrected-turn", status: "running", workSegments: [],
    items: [{ id: "output", sequence: 1, kind: "message", message: provisional }],
  };
  const contentRenderer = {
    resolveArtifact: async (artifactId: string) => ({ artifactId, mimeType: "video/mp4", url: "https://media.example/video.mp4" }),
  };
  const render = async (value: AgentConversationTurn) => {
    await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [value], contentRenderer })));
  };
  await render(base);
  const video = container.querySelector("video");
  assert.ok(video);
  video.currentTime = 17;
  const qualifier = container.querySelectorAll(".zebra-agent-content__text")[1];
  await render({ ...base, assistantMessage: message(provisional.id, provisional.content) });
  assert.equal(container.querySelectorAll(".zebra-agent-content__text")[1], qualifier);
  assert.equal(container.querySelector("video"), video);
  const unchanged = selectConversationItems({ ...base, assistantMessage: message(provisional.id, provisional.content) })[0];
  assert.ok(unchanged?.kind === "message");
  assert.equal(unchanged.message.parts, provisional.parts);
  const final = message(provisional.id, "Corrected final answer");
  await render({ ...base, status: "completed", assistantMessage: final });
  await settleAnnouncements();
  assert.equal(container.querySelector(".zebra-agent-content__text")?.textContent, "Corrected final answer");
  assert.equal(container.querySelector("video"), video);
  assert.equal(video.currentTime, 17);
  assert.equal(container.querySelectorAll(".zebra-agent-content__text")[1], qualifier);
  assert.equal(qualifier?.textContent, "Illustrative only; not live verification");
  assert.deepEqual([...container.querySelector(".zebra-agent-content")!.children].map((node) => node.textContent?.startsWith("Corrected")
    ? "intro" : node.querySelector("video") ? "video" : "qualifier"), ["intro", "video", "qualifier"]);
  assert.match(container.querySelector(".zebra-agent-turn__announcement")?.textContent ?? "", /Corrected final answer/);
  assert.doesNotMatch(container.textContent ?? "", /Draft/);
  const selected = selectConversationItems({ ...base, assistantMessage: final })[0];
  assert.equal(selected?.kind === "message" && selected.message.parts?.[0]?.id, "answer-text");
  assert.equal(selected?.kind === "message" && selected.message.parts?.[1], provisional.parts?.[1]);
  assert.equal(selected?.kind === "message" && selected.message.parts?.[2], provisional.parts?.[2]);
  await act(async () => root.unmount());
  dom.window.close();
});

test("text-only corrections retain independent text slots, IDs and aggregate suffixes", () => {
  const video = { id: "answer:text", type: "video" as const, state: "ready" as const, artifactId: "video", mimeType: "video/mp4", title: "Recording" };
  const text = { id: "first-text", type: "text" as const, state: "ready" as const, format: "markdown" as const, text: "Draft" };
  const qualifier = { ...text, id: "last-text", text: "Independent qualifier" };
  for (const parts of [[text, video, qualifier], [video]]) {
    const provisional: AgentMessage = { ...message("answer", "Draft", "streaming"), parts };
    const base: AgentConversationTurn = {
      id: "reconcile", status: "completed", workSegments: [],
      items: [{ id: "output", kind: "message", message: provisional }],
    };
    const original = JSON.stringify(parts);
    const selected = selectConversationItems({ ...base, assistantMessage: message("answer", "Corrected final answer") })[0];
    assert.ok(selected?.kind === "message");
    assert.deepEqual(selected.message.parts?.filter((part) => part.type === "text").map((part) => part.text),
      parts.includes(qualifier) ? ["Corrected final answer", qualifier.text] : ["Corrected final answer"]);
    assert.equal(selected.message.parts?.find((part) => part.type === "video"), video);
    assert.equal(new Set(selected.message.parts?.map((part) => part.id)).size, selected.message.parts?.length);
    assert.equal(JSON.stringify(parts), original);
    const cleared = selectConversationItems({ ...base, assistantMessage: message("answer", "") })[0];
    assert.ok(cleared?.kind === "message");
    assert.doesNotMatch(JSON.stringify(cleared.message.parts), /Draft/);
    assert.equal(cleared.message.parts?.find((part) => part.type === "video"), video);
    if (parts.includes(qualifier)) assert.equal(cleared.message.parts?.[2], qualifier);
    const fullCorrection = selectConversationItems({ ...base, assistantMessage: message("answer", "Corrected final answer\nIndependent qualifier") })[0];
    if (parts.includes(qualifier)) {
      assert.ok(fullCorrection?.kind === "message");
      assert.deepEqual(fullCorrection.message.parts?.filter((part) => part.type === "text").map((part) => part.text), ["Corrected final answer", qualifier.text]);
      for (const content of ["Corrected final answer. Independent qualifier", "Corrected final answer\n\nIndependent qualifier"]) {
        const inline = selectConversationItems({ ...base, assistantMessage: message("answer", content) })[0];
        assert.ok(inline?.kind === "message");
        assert.deepEqual(inline.message.parts?.filter((part) => part.type === "text").map((part) => part.text),
          [content.startsWith("Corrected final answer.") ? "Corrected final answer." : "Corrected final answer", qualifier.text]);
      }
      const stale = { ...base, items: [{ id: "output", kind: "message" as const, message: { ...provisional, parts: [{ ...text, text: "Later draft" }, video, qualifier] } }] };
      const restored = selectConversationItems({ ...stale, assistantMessage: message("answer", "Draft") })[0];
      assert.ok(restored?.kind === "message");
      assert.deepEqual(restored.message.parts?.filter((part) => part.type === "text").map((part) => part.text), ["Draft", qualifier.text]);
    }
    const aggregate = { ...base, items: [{ id: "output", kind: "message" as const, message: { ...provisional, content: "Draft\nIndependent qualifier" } }] };
    if (!parts.includes(qualifier)) continue;
    const unchanged = selectConversationItems({ ...aggregate, assistantMessage: message("answer", "Draft\nIndependent qualifier") })[0];
    assert.equal(unchanged?.kind === "message" && unchanged.message.parts, parts);
    const corrected = selectConversationItems({ ...aggregate, assistantMessage: message("answer", "Corrected final answer\nIndependent qualifier") })[0];
    assert.ok(corrected?.kind === "message");
    assert.deepEqual(corrected.message.parts?.map((part) => part.id), parts.map((part) => part.id));
    assert.deepEqual(corrected.message.parts?.filter((part) => part.type === "text").map((part) => part.text), ["Corrected final answer", qualifier.text]);
  }
});

test("a persistent initially empty live region announces complete arrivals after insertion without history or replay spam", async () => {
  const { container, dom, root } = await mount();
  const base: AgentConversationTurn = { id: "arrivals", status: "running", workSegments: [] };
  const history: AgentConversationItem = { id: "history", sequence: 1, kind: "message", message: message("history", "Older history") };
  const render = async (items: readonly AgentConversationItem[]) => {
    await act(async () => root.render(createElement(AgentConversationTimeline, { turns: [{ ...base, items }] })));
  };
  await render([history]);
  await settleAnnouncements();
  const announcement = container.querySelector(".zebra-agent-turn__announcement");
  assert.ok(announcement);
  assert.equal(announcement.textContent, "");
  const mutations: string[] = [];
  const observer = new dom.window.MutationObserver(() => mutations.push(announcement.textContent ?? ""));
  observer.observe(announcement, { characterData: true, childList: true, subtree: true });
  const first: AgentConversationItem = { id: "first", sequence: 2, kind: "message", message: message("first", "Complete milestone") };
  await render([history, first]);
  await settleAnnouncements();
  assert.equal(container.querySelector(".zebra-agent-turn__announcement"), announcement);
  assert.equal(container.querySelectorAll(".zebra-agent-turn__announcement").length, 1);
  assert.equal(announcement.textContent, "Complete milestone");
  assert.ok(mutations.includes("Complete milestone"));
  mutations.length = 0;
  await render([{ ...history }, { ...first }]);
  await settleAnnouncements();
  assert.equal(mutations.length, 0);
  const second: AgentConversationItem = { id: "second", sequence: 3, kind: "message", message: message("second", "Complete milestone") };
  await render([history, first, second]);
  await settleAnnouncements();
  assert.ok(mutations.includes(""));
  assert.ok(mutations.includes("Complete milestone"));
  assert.equal(container.querySelector(".zebra-agent-turn__announcement"), announcement);
  observer.disconnect();
  await act(async () => root.unmount());
  dom.window.close();
});

test("AgentChat scrollKey scopes a persistent live region through empty history, omissions and navigation", async () => {
  const { container, dom, root } = await mount();
  const base: AgentConversationTurn = { id: "same-turn-id", status: "running", workSegments: [] };
  const item = (id: string, content: string): Extract<AgentConversationItem, { kind: "message" }> => ({ id, kind: "message", message: message(id, content) });
  const render = async (scrollKey: string, items: readonly AgentConversationItem[] | undefined) => {
    await act(async () => root.render(createElement(AgentChat, {
      composer: createElement("div", null, "Composer"), emptyState: createElement("p", null, "Loading history"),
      scrollKey, turns: items === undefined ? [] : [{ ...base, items }],
    })));
    await settleAnnouncements();
  };
  await render("session-a", undefined);
  const region = container.querySelector(".zebra-agent-turn__announcement");
  assert.ok(region);
  assert.equal(region.textContent, "");
  const history = item("history", "History A");
  await render("session-a", [history]);
  assert.equal(region.textContent, "");
  const first = item("first", "Complete milestone");
  await render("session-a", [history, first]);
  assert.equal(region.textContent, "Complete milestone");
  const mutations: string[] = [];
  const observer = new dom.window.MutationObserver(() => mutations.push(region.textContent ?? ""));
  observer.observe(region, { characterData: true, childList: true, subtree: true });
  await render("session-a", undefined);
  await render("session-a", [{ ...history, message: { ...history.message } }, first]);
  assert.equal(mutations.length, 0);
  await render("session-a", [history, { ...first, message: message("first", "Complete milestone", "streaming") }]);
  await render("session-a", [history, first]);
  assert.equal(mutations.length, 0);
  await render("session-a", [history, first, item("second", "Complete milestone")]);
  assert.ok(mutations.includes(""));
  assert.ok(mutations.includes("Complete milestone"));
  await render("session-b", undefined);
  assert.equal(region.textContent, "");
  await render("session-b", [item("history", "History B"), item("first", "Old milestone B")]);
  assert.equal(region.textContent, "");
  await render("session-b", [item("history", "History B"), item("first", "Old milestone B"), item("third", "Live result B")]);
  assert.equal(region.textContent, "Live result B");
  await render("session-c", [item("history", "History B"), item("first", "Old milestone B"), item("third", "Live result B")]);
  assert.equal(region.textContent, "");
  await render("session-c", [item("history", "History C")]);
  assert.equal(region.textContent, "");
  await render("session-c", [item("history", "History C"), item("new", "Live result C")]);
  assert.equal(region.textContent, "Live result C");
  await render("session-c", [item("history", "History C"), item("new", "Live result C"), item("third", "Live result B")]);
  assert.equal(region.textContent, "Live result B");
  await render("session-d", [item("history", "History C"), item("new", "Live result C"), item("third", "Live result B")]);
  assert.equal(region.textContent, "");
  await render("session-d", [item("history", "History C"), item("new", "Live result C"), item("third", "Live result B"), item("next", "Live result D")]);
  assert.equal(region.textContent, "Live result D");
  assert.equal(container.querySelector(".zebra-agent-turn__announcement"), region);
  assert.equal(container.querySelectorAll(".zebra-agent-turn__announcement").length, 1);
  observer.disconnect();
  await act(async () => root.unmount());
  dom.window.close();
});

test("recreated final confirmation views reuse completed announcement text", async () => {
  const { container, dom, root } = await mount();
  let extractions = 0;
  const history = message("history", "History");
  const parts = [{ id: "text", type: "text" as const, state: "ready" as const, format: "plain" as const, text: "History" }];
  const filter = parts.filter.bind(parts);
  Object.defineProperty(parts, "filter", { get: () => { extractions += 1; return filter; } });
  const turn: AgentConversationTurn = { id: "history", status: "completed", workSegments: [] };
  const render = async (value: AgentMessage) => {
    await act(async () => root.render(createElement(AgentConversationAnnouncement, {
      turns: [{ turn, items: [{ id: "output", kind: "message", message: value }] }],
    })));
  };
  await render({ ...history, parts });
  assert.equal(extractions, 1);
  await render({ ...history, parts });
  assert.equal(extractions, 1);
  await render({ ...history, parts: parts.map((part) => ({ ...part })) });
  assert.equal(container.querySelector(".zebra-agent-turn__announcement")?.textContent, "");
  await render({ ...history, content: "Corrected history", parts: [{ ...parts[0]!, text: "Corrected history" }] });
  await settleAnnouncements();
  assert.equal(container.querySelector(".zebra-agent-turn__announcement")?.textContent, "Corrected history");
  await act(async () => root.unmount());
  dom.window.close();
});

test("rapid identical completions survive streaming and omissions, with scope/unmount timer cleanup", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const { container, dom, root } = await mount();
  const base: AgentConversationTurn = { id: "rapid", status: "running", workSegments: [] };
  const first: AgentConversationItem = { id: "first", kind: "message", message: message("first", "Same completion") };
  const second: AgentConversationItem = { id: "second", kind: "message", message: message("second", "Same completion") };
  const render = async (items: readonly AgentConversationItem[], scrollKey = "session-a") => {
    await act(async () => root.render(createElement(StrictMode, null,
      createElement(AgentConversationTimeline, { scrollKey, turns: [{ ...base, items }] }))));
  };
  const flush = async () => { await act(async () => context.mock.timers.tick(1)); };
  await render([]);
  await render([first]);
  await render([first, second]);
  await render([{ id: "draft", kind: "message", message: message("draft", "Streaming", "streaming") }]);
  await flush();
  assert.equal(container.querySelector(".zebra-agent-turn__announcement")?.textContent, "Same completion\nSame completion");
  await render([first, second]);
  await flush();
  const region = container.querySelector(".zebra-agent-turn__announcement");
  assert.equal(region?.textContent, "Same completion\nSame completion");
  await render([first, second, { id: "old-pending", kind: "message", message: message("old-pending", "Stale conversation") }]);
  await render([first], "session-b");
  await flush();
  assert.equal(region?.textContent, "");
  assert.equal(container.querySelector(".zebra-agent-turn__announcement"), region);
  await render([first, second], "session-b");
  await act(async () => root.unmount());
  await flush();
  assert.equal(container.textContent, "");
  dom.window.close();
});

test("token renders share each snapshot's selection and reuse historical announcement text", async () => {
  const { container, dom, root } = await mount();
  let selections = 0;
  let textReads = 0;
  const history = message("history", "History");
  Object.defineProperty(history, "parts", { get: () => { textReads += 1; return undefined; } });
  const items: readonly AgentConversationItem[] = [{ id: "history", kind: "message", message: history }];
  const historical: AgentConversationTurn = { id: "history-turn", status: "completed", workSegments: [] };
  Object.defineProperty(historical, "items", { configurable: true, get: () => { selections += 1; return items; } });
  const render = async (content: string) => {
    await act(async () => root.render(createElement(AgentConversationTimeline, {
      renderMessageContent: () => null,
      turns: [historical, { id: "live", status: "running", workSegments: [], items: [{ id: "draft", kind: "message", message: message("draft", content, "streaming") }] }],
    })));
  };
  await render("One");
  assert.equal(selections, 1);
  assert.equal(textReads, 1);
  await render("One two");
  await render("One two three");
  assert.equal(selections, 3);
  assert.equal(textReads, 1);
  Object.defineProperty(historical, "items", { configurable: true,
    value: [{ id: "history", kind: "message", message: message("history", "Corrected history") }] });
  await render("One two three four");
  await settleAnnouncements();
  assert.equal(container.querySelector(".zebra-agent-turn__announcement")?.textContent, "Corrected history");
  await act(async () => root.unmount());
  dom.window.close();
});
