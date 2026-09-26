import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";

import {
  AgentChat,
  AgentComposer,
  AgentRunStatus,
  type AgentChatProps,
  type AgentComposerProps,
  type AgentRunStatusProps,
} from "../src/index.ts";
import type { AgentRunState } from "@zebra-agent/ui-contracts";

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
  const root = createRoot(container);
  return { container, dom, root };
}

test("AgentRunStatus keeps every lifecycle and terminal outcome distinct", async () => {
  const { container, dom, root } = await mount();
  const states: readonly [AgentRunState, string][] = [
    [{ phase: "submitting", availableActions: [] }, "Submitting locally"],
    [{ phase: "accepted", availableActions: [] }, "Accepted by server"],
    [{ phase: "queued", queuePosition: 3, availableActions: [] }, "Queued · position 3"],
    [{ phase: "running", availableActions: [] }, "Working"],
    [{ phase: "waiting_for_user", availableActions: [] }, "Waiting for your input"],
    [{ phase: "terminal", outcome: "completed", availableActions: [] }, "Completed"],
    [{ phase: "terminal", outcome: "partial", availableActions: [] }, "Partially completed"],
    [{ phase: "terminal", outcome: "blocked", availableActions: [] }, "Blocked"],
    [{ phase: "terminal", outcome: "failed", availableActions: [] }, "Failed"],
    [{ phase: "terminal", outcome: "cancelled", availableActions: [] }, "Cancelled"],
  ];
  for (const [state, expected] of states) {
    await act(async () => root.render(createElement(AgentRunStatus, { state })));
    assert.match(container.textContent ?? "", new RegExp(expected.replace("·", "\\·")));
  }
  await act(async () => root.unmount());
  dom.window.close();
});

test("reconnect, resume and retry are separate and reconciliation cannot replay", async () => {
  const calls: string[] = [];
  const { container, dom, root } = await mount();
  const callbacks: Omit<AgentRunStatusProps, "state"> = {
    onReconnect: () => calls.push("reconnect"),
    onResume: () => calls.push("resume"),
    onRetry: () => calls.push("retry"),
  };
  const render = async (state: AgentRunState) => act(async () => {
    root.render(createElement(AgentRunStatus, { ...callbacks, state }));
  });

  await render({ phase: "reconciling", availableActions: ["retry"], diagnosticId: "diag-safe" });
  assert.equal(container.querySelectorAll("button").length, 0);
  assert.match(container.textContent ?? "", /Diagnostic ID: diag-safe/);

  await render({ phase: "disconnected", availableActions: ["reconnect", "resume", "retry"] });
  assert.deepEqual([...container.querySelectorAll("button")].map((button) => button.textContent), ["Reconnect"]);
  await act(async () => (container.querySelector("button") as HTMLButtonElement).click());

  await render({ phase: "paused", availableActions: ["resume", "retry"] });
  assert.deepEqual([...container.querySelectorAll("button")].map((button) => button.textContent), ["Continue task"]);
  await act(async () => (container.querySelector("button") as HTMLButtonElement).click());

  await render({ phase: "terminal", outcome: "failed", availableActions: ["retry"] });
  await act(async () => (container.querySelector("button") as HTMLButtonElement).click());
  assert.deepEqual(calls, ["reconnect", "resume", "retry"]);

  await render({ phase: "terminal", outcome: "blocked", availableActions: ["resume", "resume"] });
  assert.equal(container.querySelectorAll("button").length, 1);
  await act(async () => root.unmount());
  dom.window.close();
});

test("AgentChat keeps one controlled Composer boundary from empty to active conversation", async () => {
  const { container, dom, root } = await mount();
  const composerProps: AgentComposerProps = {
    attachments: [{ id: "brief", isImage: false, name: "brief.md" }],
    busy: false,
    capabilityOptions: [],
    capabilityValue: "general",
    canContinue: false,
    disabled: false,
    metrics: { cacheHitRate: null, contextLimit: null, contextPercent: null, contextTokens: null },
    modelOptions: [],
    modelValue: "default",
    onCapabilityChange: () => undefined,
    onContinue: () => undefined,
    onFilesSelected: () => undefined,
    onModelChange: () => undefined,
    onPause: () => undefined,
    onReasoningChange: () => undefined,
    onRemoveAttachment: () => undefined,
    onSubmit: () => undefined,
    onSuggestionPick: () => undefined,
    onValueChange: () => undefined,
    pausing: false,
    queueCount: 0,
    reasoningOptions: [],
    reasoningValue: "high",
    suggestions: [],
    value: "Keep this draft",
  };
  const composer = createElement(AgentComposer, composerProps);
  const base: AgentChatProps = {
    activities: [],
    activityExpanded: false,
    composer,
    emptyState: createElement("p", null, "Ready when you are"),
    messages: [],
    onActivityExpandedChange: () => undefined,
    runStatus: { state: { phase: "idle", availableActions: [] } },
  };

  await act(async () => root.render(createElement(AgentChat, base)));
  const initial = container.querySelector("textarea") as HTMLTextAreaElement;
  initial.focus();
  assert.equal(dom.window.document.activeElement, initial);

  await act(async () => root.render(createElement(AgentChat, {
    ...base,
    messages: [{ id: "user-1", role: "user", content: "Keep this draft", status: "complete" }],
    runStatus: { state: { phase: "accepted", availableActions: [] } },
  })));
  const active = container.querySelector("textarea") as HTMLTextAreaElement;
  assert.equal(active, initial);
  assert.equal(active.value, "Keep this draft");
  assert.equal(dom.window.document.activeElement, active);
  assert.match(container.textContent ?? "", /brief\.md/);

  await act(async () => root.render(createElement(AgentChat, {
    ...base,
    activities: [{ activityId: "stale", kind: "tool", status: "running", title: "Stale activity" }],
    messages: [{ id: "user-1", role: "user", content: "Keep this draft", status: "complete" }],
    runStatus: { state: { phase: "terminal", outcome: "failed", availableActions: ["retry"] } },
  })));
  assert.equal((container.querySelector("details") as HTMLDetailsElement).open, false);
  assert.match((container.querySelector("details summary") as HTMLElement).textContent ?? "", /Failed/);

  await act(async () => root.unmount());
  dom.window.close();
});
