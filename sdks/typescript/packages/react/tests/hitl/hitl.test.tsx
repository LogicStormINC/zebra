import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";

import {
  ZebraHitlProvider,
  useZebraApproval,
  useZebraClarification,
  type ZebraHitlSnapshot,
  type ZebraHitlSource,
} from "../../src/index.ts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

class InterruptStore implements ZebraHitlSource {
  private listeners = new Set<() => void>();

  constructor(private snapshot: ZebraHitlSnapshot) {}

  getSnapshot = (): ZebraHitlSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  publish(snapshot: ZebraHitlSnapshot): void {
    this.snapshot = snapshot;
    for (const listener of this.listeners) listener();
  }
}

function domRoot(): { dom: JSDOM; root: Root } {
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  const container = dom.window.document.getElementById("root");
  assert.ok(container !== null);
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
  });
  return { dom, root: createRoot(container) };
}

test("durable source replays an open interrupt and publishes the next one", async () => {
  const store = new InterruptStore({
    approval: {
      approval_id: "approval-1",
      tool_name: "deploy.release",
      reason: "Writes production state",
    },
    clarification: null,
  });
  let current: ReturnType<typeof useZebraApproval>["approval"] = null;
  let clarification: ReturnType<typeof useZebraClarification>["clarification"] = null;
  function Fixture() {
    current = useZebraApproval().approval;
    clarification = useZebraClarification().clarification;
    return null;
  }
  const { dom, root } = domRoot();
  await act(async () => {
    root.render(createElement(ZebraHitlProvider, {
      source: store,
      controller: true,
      controllerFenceToken: "controller-fence-a",
      onDecide: async () => {},
      onRespond: async () => {},
      children: createElement(Fixture),
    }));
  });
  assert.equal(current?.approval_id, "approval-1");

  await act(async () => {
    store.publish({
      approval: null,
      clarification: {
        clarification_id: "clarification-1",
        question: "Which environment?",
        choices: ["staging", "production"],
      },
    });
  });
  assert.equal(current, null);
  assert.equal(clarification?.clarification_id, "clarification-1");
  await act(async () => root.unmount());
  dom.window.close();
});

test("observer and stale controller callbacks fail before submission", async () => {
  let decide: ReturnType<typeof useZebraApproval>["decide"] | null = null;
  let submissions = 0;
  function Fixture() {
    decide = useZebraApproval().decide;
    return null;
  }
  const { dom, root } = domRoot();
  const render = (controller: boolean, fence: string) =>
    createElement(ZebraHitlProvider, {
      approval: {
        approval_id: "approval-1",
        tool_name: "deploy.release",
        reason: "Writes production state",
      },
      controller,
      controllerFenceToken: fence,
      onDecide: async () => { submissions += 1; },
      onRespond: async () => {},
      children: createElement(Fixture),
    });
  await act(async () => root.render(render(false, "controller-fence-a")));
  await assert.rejects(() => decide!("approve"), /observer/);

  await act(async () => root.render(render(true, "controller-fence-a")));
  const staleDecide = decide!;
  await act(async () => root.render(render(true, "controller-fence-b")));
  await assert.rejects(() => staleDecide("approve"), /fence is stale/);
  assert.equal(submissions, 0);
  await act(async () => root.unmount());
  dom.window.close();
});

test("duplicate decisions submit once and free-text clarification remains valid", async () => {
  let decide: ReturnType<typeof useZebraApproval>["decide"] | null = null;
  let respond: ReturnType<typeof useZebraClarification>["respond"] | null = null;
  const decisions: Array<[string, string]> = [];
  const responses: Array<[string, string]> = [];
  function Fixture() {
    decide = useZebraApproval().decide;
    respond = useZebraClarification().respond;
    return null;
  }
  const { dom, root } = domRoot();
  await act(async () => {
    root.render(createElement(ZebraHitlProvider, {
      approval: {
        approval_id: "approval-1",
        tool_name: "deploy.release",
        reason: "Writes production state",
      },
      clarification: {
        clarification_id: "clarification-1",
        question: "Describe the target",
        choices: [],
      },
      controller: true,
      controllerFenceToken: "controller-fence-a",
      onDecide: async (decision, key) => { decisions.push([decision, key]); },
      onRespond: async (choice, key) => { responses.push([choice, key]); },
      children: createElement(Fixture),
    }));
  });
  await act(async () => Promise.all([decide!("reject"), decide!("reject")]));
  await act(async () => respond!("staging-eu"));
  assert.deepEqual(decisions, [["reject", "hitl-approval:approval-1"]]);
  assert.deepEqual(responses, [["staging-eu", "hitl-clarification:clarification-1"]]);
  await act(async () => root.unmount());
  dom.window.close();
});
