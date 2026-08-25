/**
 * Import-level smoke test: the React package parses and exposes the
 * documented hook surface without a DOM renderer. Full Strict-Mode /
 * unmount / multi-tab behaviors need a DOM runner (jsdom + vitest) and
 * are registered as the SDK follow-up (CLIENT-REACT-HOOKS-01).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ZebraAgentProvider,
  useZebraAction,
  useZebraAgentState,
  useZebraClientStatus,
  useZebraReadable,
  useZebraTask,
} from "../src/index.ts";
import {
  ZebraHitlProvider,
  useZebraApproval,
  useZebraClarification,
} from "../src/hitl/index.ts";

test("react package exposes the ADR-CLIENT-01 hook surface", () => {
  assert.equal(typeof ZebraAgentProvider, "function");
  assert.equal(typeof useZebraReadable, "function");
  assert.equal(typeof useZebraAction, "function");
  assert.equal(typeof useZebraClientStatus, "function");
  assert.equal(typeof useZebraTask, "function");
  assert.equal(typeof useZebraAgentState, "function");
  assert.equal(typeof ZebraHitlProvider, "function");
  assert.equal(typeof useZebraApproval, "function");
  assert.equal(typeof useZebraClarification, "function");
});
