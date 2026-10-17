import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";

import { AgentChat, AgentUsageAnalytics, type AgentChatProps, type AgentUsageSnapshot } from "../src/index.ts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

test("AgentChat renders the finite public surfaces and keeps Host actions controlled", async () => {
  const calls: string[] = [];
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
  const root = createRoot(container);
  const base: AgentChatProps = {
    activities: [{ activityId: "tool-1", kind: "tool", status: "completed", title: "Read workspace" }],
    activityExpanded: false,
    approval: {
      approval: { approval_id: "approval-1", tool_name: "deploy.release", reason: "Writes production state" },
      onDecision: (decision) => calls.push(`decision:${decision}`),
    },
    artifacts: [{ id: "report", kind: "md", name: "report.md", status: "ready" }],
    clarification: {
      clarification: { clarification_id: "question-1", question: "Choose a target", choices: ["Staging", "Production"] },
      onRespond: (choice) => calls.push(`choice:${choice}`),
    },
    composer: createElement("div", null, "Composer slot"),
    memorySettings: [{ id: "preferences", label: "Preferences", description: "Recall confirmed preferences", enabled: true }],
    messages: [
      { id: "user-1", role: "user", content: "Inspect it", status: "complete" },
      { id: "agent-1", role: "assistant", content: "Inspection complete", status: "complete" },
    ],
    onActivityExpandedChange: (expanded) => calls.push(`expanded:${expanded}`),
    onArtifactOpen: (id) => calls.push(`artifact:${id}`),
    onMemoryToggle: (id, enabled) => calls.push(`memory:${id}:${enabled}`),
    themeTokens: {
      accent: "#66ccff",
      composerRadius: "20px",
      contentWidth: "840px",
      surface: "#101820",
    },
  };
  const render = async (props: AgentChatProps) => act(async () => root.render(createElement(AgentChat, props)));

  await render(base);
  const chat = container.querySelector(".zebra-agent-chat") as HTMLElement;
  assert.equal(chat.style.getPropertyValue("--zebra-agent-accent"), "#66ccff");
  assert.equal(chat.style.getPropertyValue("--zebra-agent-composer-radius"), "20px");
  assert.equal(chat.style.getPropertyValue("--zebra-agent-content-width"), "840px");
  assert.equal(chat.style.getPropertyValue("--zebra-agent-surface"), "#101820");
  assert.match(container.textContent ?? "", /Inspection complete/);
  assert.match(container.textContent ?? "", /deploy\.release/);
  assert.equal((container.querySelector("details") as HTMLDetailsElement).open, false);

  const buttons = [...container.querySelectorAll("button")];
  await act(async () => {
    buttons.find((button) => button.textContent === "Approve")?.click();
    buttons.find((button) => button.textContent === "Production")?.click();
    buttons.find((button) => button.textContent === "Open")?.click();
    (container.querySelector('input[type="checkbox"]') as HTMLInputElement).click();
  });
  assert.deepEqual(calls, [
    "decision:approve",
    "choice:Production",
    "artifact:report",
    "memory:preferences:false",
  ]);

  await render({ ...base, activities: [{ ...base.activities[0]!, status: "running" }] });
  // Running indicators must not override the Host's explicit collapsed state.
  assert.equal((container.querySelector("details") as HTMLDetailsElement).open, false);

  await render({
    ...base,
    activities: [{ ...base.activities[0]!, status: "completed" }],
    activityExpanded: true,
    runStatus: { state: { phase: "terminal", outcome: "completed", availableActions: [] } },
  });
  assert.equal(calls.at(-1), "expanded:false");

  await act(async () => root.unmount());
  dom.window.close();
});

test("AgentUsageAnalytics renders provider usage without inventing billing limits", async () => {
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, Event: dom.window.Event,
    Node: dom.window.Node, HTMLElement: dom.window.HTMLElement,
  });
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(container);
  const counts = { input_tokens: 8, output_tokens: 2, total_tokens: 10, reasoning_tokens: 1,
    cache_hit_tokens: 0, cache_miss_tokens: 0, model_calls: 1, unmetered_calls: 0,
    tool_calls: 0, messages: 1 };
  const snapshot: AgentUsageSnapshot = {
    schema_version: 1, source: "committed_cloud_events",
    period: { days: 7, start: "2026-10-01", end: "2026-10-07", timezone: "UTC" },
    totals: counts, daily: [{ date: "2026-10-01", ...counts }],
    daily_models: [{ date: "2026-10-01", model: "model-a", model_calls: 1, total_tokens: 10 }],
    models: [{ model: "model-a", model_calls: 1, total_tokens: 10 }],
    tools: [], tasks: [{ task_id: "task-1", title: "Research", ...counts }],
  };
  await act(async () => root.render(createElement(AgentUsageAnalytics, {
    snapshot, days: 7, onDaysChange: () => undefined,
  })));
  assert.match(container.textContent ?? "", /Research/);
  assert.match(container.textContent ?? "", /10/);
  assert.doesNotMatch(container.textContent ?? "", /积分已用|额度已用/);
  await act(async () => root.unmount());
  dom.window.close();
});
