import assert from "node:assert/strict";
import { resolveStoredConversation } from "../src/lib/use-workspace-selection.ts";

const conversations = [{ key: "durable-task", label: "Durable task", group: "12:00" }];

assert.equal(resolveStoredConversation("durable-task", conversations, "home"), "durable-task");
assert.equal(resolveStoredConversation("hidden-task", conversations, "home"), "home");
assert.equal(resolveStoredConversation(null, conversations, "home"), "home");
