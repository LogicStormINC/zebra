import type { SessionCommitResponse, SessionPullRequestResponse } from "../types";
import type { SessionResultSurface } from "./session-results";

export interface CommitInput {
  message: string;
}

export interface PullRequestInput {
  title: string;
  body: string;
  base_branch: string;
  head_branch?: string;
}

export interface SessionDeliveryController {
  busy: boolean;
  commitResult: SessionCommitResponse | undefined;
  errorText: string | null;
  pullRequestResult: SessionPullRequestResponse | undefined;
  commit: (input: CommitInput) => Promise<SessionCommitResponse>;
  planPullRequest: (input: PullRequestInput) => Promise<SessionPullRequestResponse>;
  executePullRequest: (input: PullRequestInput) => Promise<SessionPullRequestResponse>;
}

export function projectDeliveryAvailability(
  status: string | undefined,
  surface: SessionResultSurface | null,
  policyProfile?: string,
) {
  const settled = ["ready", "completed", "failed", "cancelled", "canceled", "stopped"].includes(status ?? "");
  const hasEvidence = Boolean(surface?.diff);
  const policyAllowsDelivery = policyProfile === "full_access";
  return {
    canCommit: settled && hasEvidence && policyAllowsDelivery && surface?.diff?.clean === false,
    canPlanPullRequest: settled && hasEvidence && policyAllowsDelivery,
    reason: !status
      ? "当前会话状态不可用"
      : !settled
        ? "任务仍在执行或等待处理"
        : !hasEvidence
          ? "尚未读取到工作区变更证据"
          : !policyAllowsDelivery
            ? "当前权限策略不允许 Commit 或 Pull Request"
            : surface?.diff?.clean
              ? "工作区没有待提交变更"
              : null,
  };
}

export function buildPullRequestPayload(input: PullRequestInput, execute = false) {
  return { ...input, dry_run: !execute };
}
