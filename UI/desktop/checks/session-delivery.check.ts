import assert from "node:assert/strict";
import { buildPullRequestPayload, projectDeliveryAvailability } from "../src/lib/session-delivery.ts";

const surface = (clean: boolean) => ({ diff: { clean }, artifacts: null, deliveryAudit: null }) as never;
assert.equal(projectDeliveryAvailability(undefined, surface(false), "full_access").reason, "当前会话状态不可用");
assert.equal(projectDeliveryAvailability("running", surface(false), "full_access").canCommit, false);
assert.equal(projectDeliveryAvailability("completed", null, "full_access").canPlanPullRequest, false);
assert.equal(projectDeliveryAvailability("completed", surface(false), "workspace_write").canCommit, false);
assert.equal(projectDeliveryAvailability("completed", surface(false), "full_access").canCommit, true);
assert.equal(projectDeliveryAvailability("completed", surface(true), "full_access").canCommit, false);
assert.equal(projectDeliveryAvailability("failed", surface(false), "full_access").canPlanPullRequest, true);

const input = { title: "Ship", body: "Reviewed", base_branch: "main", head_branch: "feature/zebra" };
assert.equal(buildPullRequestPayload(input).dry_run, true);
assert.equal(buildPullRequestPayload(input, true).dry_run, false);
