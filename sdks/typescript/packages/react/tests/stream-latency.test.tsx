import assert from "node:assert/strict";
import test from "node:test";
import React, { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { AgentMessageList } from "../src/components/agent-message-list.tsx";
import { ConversationStreamReducer } from "../../client-core/src/conversation_stream.ts";
import type { AgentMessage } from "@zebra-agent/ui-contracts";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

test("recorded drafts display before commit without re-rendering unchanged historical content", async () => {
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, Node: dom.window.Node, HTMLElement: dom.window.HTMLElement });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  const { createRoot } = await import("react-dom/client");
  const container = dom.window.document.getElementById("root")!;
  const root = createRoot(container);
  const reducer = new ConversationStreamReducer();
  const history: AgentMessage[] = [0, 1, 2].map(index => ({ id: `history-${index}`, role: "assistant", content: "Stored content", status: "complete" }));
  const renders = new Map<string, number>();
  const renderContent = (message: AgentMessage) => {
    renders.set(message.id, (renders.get(message.id) ?? 0) + 1);
    return createElement("span", { "data-message": message.id }, message.content);
  };
  const render = (labels?: { draft: string }) => act(async () => root.render(createElement(AgentMessageList, { messages: [...history, ...reducer.snapshot()], renderContent, labels })));
  try {
    await render();
    for (let offset = 0; offset < 40; offset++) {
      reducer.observe({ type: "CUSTOM", name: "zebra.stream.draft", value: { message_id: "message:call", generation_id: "g", offset, content_delta: "字" } });
      await render({ draft: "Draft" });
      if (offset === 0) {
        assert.equal(container.querySelector('[data-message="message:call"]')?.textContent, "字");
        assert.equal(container.querySelector(".zebra-agent-message__draft")?.textContent, "Draft");
      }
    }
    for (const message of history) assert.equal(renders.get(message.id), 1, `${message.id} re-rendered during live text`);
    await render({ draft: "临时草稿" });
    assert.equal(container.querySelector(".zebra-agent-message__draft")?.textContent, "临时草稿");
    reducer.observe({ type: "CUSTOM", name: "zebra.answer_committed", value: { model_call_id: "call", assistant_message: "Corrected final" } });
    await render();
    assert.equal(container.querySelector('[data-message="message:call"]')?.textContent, "Corrected final");
    assert.equal(container.querySelector(".zebra-agent-message__draft"), null);
    assert.equal(container.querySelectorAll('[data-message="message:call"]').length, 1);
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
  }
});
