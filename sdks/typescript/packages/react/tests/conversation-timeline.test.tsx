import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";

import { AgentConversationTimeline } from "../src/index.ts";
import type { AgentConversationTurn } from "@zebra-agent/ui-contracts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
