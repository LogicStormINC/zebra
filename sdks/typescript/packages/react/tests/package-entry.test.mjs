import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import { renderToString } from "react-dom/server";

import {
  AgentComposer,
  AgentChat,
  AgentActivityGroup,
  AgentApproval,
  AgentArtifacts,
  AgentClarification,
  AgentMemorySettings,
  AgentMessageList,
  AgentRunStatus,
  ZebraAgentProvider,
  ZebraHitlProvider,
  useZebraApproval,
} from "@zebra-agent/react";

const require = createRequire(import.meta.url);

test("published ESM and CJS entries expose the same React surface", () => {
  const commonjs = require("@zebra-agent/react");
  assert.equal(typeof ZebraAgentProvider, "function");
  assert.equal(typeof AgentComposer, "function");
  assert.equal(typeof AgentChat, "function");
  assert.equal(typeof AgentActivityGroup, "function");
  assert.equal(typeof AgentApproval, "function");
  assert.equal(typeof AgentArtifacts, "function");
  assert.equal(typeof AgentClarification, "function");
  assert.equal(typeof AgentMemorySettings, "function");
  assert.equal(typeof AgentMessageList, "function");
  assert.equal(typeof AgentRunStatus, "function");
  assert.equal(typeof ZebraHitlProvider, "function");
  assert.equal(typeof commonjs.ZebraAgentProvider, "function");
  assert.equal(typeof commonjs.AgentComposer, "function");
  assert.equal(typeof commonjs.AgentChat, "function");
  assert.equal(typeof commonjs.AgentRunStatus, "function");
  assert.equal(typeof commonjs.ZebraHitlProvider, "function");
});

test("published React entry renders through the server boundary", () => {
  function ApprovalFixture() {
    return createElement("span", null, useZebraApproval().approval?.tool_name ?? "none");
  }
  const html = renderToString(createElement(ZebraAgentProvider, {
    config: {
      baseUrl: "https://bff.example",
      clientSessionId: "11111111-1111-4111-8111-111111111111",
      sessionCredential:
        "11111111-1111-4111-8111-111111111111:session-secret-value",
    },
    frontendAppId: "package-entry-test",
    profileRevision: 1,
    profileDigest: "a".repeat(64),
    children: createElement(ZebraHitlProvider, {
      approval: {
        approval_id: "approval-1",
        reason: "package entry test",
        tool_name: "fixture.read",
      },
      controller: true,
      onDecide: async () => undefined,
      onRespond: async () => undefined,
      children: createElement(ApprovalFixture),
    }),
  }));
  assert.match(html, /fixture\.read/);
});
