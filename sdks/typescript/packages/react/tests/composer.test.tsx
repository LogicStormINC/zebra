import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";

import { AgentComposer, type AgentComposerProps } from "../src/index.ts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

test("AgentComposer keeps host actions controlled and switches run actions safely", async () => {
  const calls: string[] = [];
  const props: AgentComposerProps = {
    attachments: [{ id: "brief", isImage: false, name: "brief.md" }],
    busy: false,
    capabilityOptions: [{ label: "Research", value: "research" }],
    capabilityValue: "research",
    canContinue: false,
    disabled: false,
    metrics: { cacheHitRate: 0.875, contextLimit: 100_000, contextPercent: 0.42, contextTokens: 42_000 },
    modelOptions: [{ label: "DeepSeek Flash", value: "deepseek-flash" }],
    modelValue: "deepseek-flash",
    onCapabilityChange: (value) => calls.push(`capability:${value}`),
    onContinue: () => calls.push("continue"),
    onFilesSelected: () => calls.push("files"),
    onModelChange: (value) => calls.push(`model:${value}`),
    onPause: () => calls.push("pause"),
    onReasoningChange: (value) => calls.push(`reasoning:${value}`),
    onRemoveAttachment: (id) => calls.push(`remove:${id}`),
    onSubmit: () => calls.push("submit"),
    onSuggestionPick: (value) => calls.push(`suggest:${value}`),
    onValueChange: (value) => calls.push(`value:${value}`),
    pausing: false,
    placeholder: "Ask Zebra",
    queueCount: 2,
    reasoningOptions: [{ label: "High", value: "high" }],
    reasoningValue: "high",
    suggestions: [{ label: "Inspect failures", value: "inspect" }],
    themeTokens: { accent: "#f4b942", composerRadius: "22px", input: "#111827" },
    value: "Investigate the worker",
  };
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    Event: dom.window.Event,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
    KeyboardEvent: dom.window.KeyboardEvent,
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: dom.window.navigator,
  });
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(container);
  const render = async (next: AgentComposerProps) => {
    await act(async () => root.render(createElement(AgentComposer, next)));
  };

  await render(props);
  const composer = container.querySelector(".zebra-agent-composer") as HTMLElement;
  assert.equal(composer.style.getPropertyValue("--zebra-agent-accent"), "#f4b942");
  assert.equal(composer.style.getPropertyValue("--zebra-agent-composer-radius"), "22px");
  assert.equal(composer.style.getPropertyValue("--zebra-agent-input"), "#111827");
  assert.match(container.textContent ?? "", /2 queued/);
  assert.match(container.textContent ?? "", /brief\.md/);
  assert.equal(container.querySelector('[aria-label="Context capacity 42%"]') !== null, true);
  assert.equal(container.querySelectorAll('[aria-label="Add attachment"]').length, 1);

  await act(async () => {
    (container.querySelector('[aria-label="Send"]') as HTMLButtonElement).click();
    (container.querySelector('[aria-label="Remove brief.md"]') as HTMLButtonElement).click();
    (container.querySelector(".zebra-agent-composer__suggestion") as HTMLButtonElement).click();
  });
  assert.deepEqual(calls, ["submit", "remove:brief", "suggest:inspect"]);

  const textarea = container.querySelector("textarea");
  assert.ok(textarea);
  await act(async () => {
    textarea.dispatchEvent(new dom.window.KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));
  });
  assert.equal(calls.at(-1), "submit");
  const submittedCalls = calls.length;
  const composingEnter = new dom.window.KeyboardEvent("keydown", { bubbles: true, key: "Enter" });
  Object.defineProperty(composingEnter, "isComposing", { value: true });
  await act(async () => textarea.dispatchEvent(composingEnter));
  assert.equal(calls.length, submittedCalls);

  await render({ ...props, busy: true });
  await act(async () => {
    (container.querySelector('[aria-label="Pause"]') as HTMLButtonElement).click();
  });
  assert.equal(calls.at(-1), "pause");

  await render({ ...props, value: "", canContinue: true });
  await act(async () => {
    (container.querySelector('[aria-label="Continue"]') as HTMLButtonElement).click();
  });
  assert.equal(calls.at(-1), "continue");

  await act(async () => root.unmount());
  dom.window.close();
});
