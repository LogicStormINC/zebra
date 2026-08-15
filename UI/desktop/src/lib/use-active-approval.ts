import { useMutation, useQuery } from "@tanstack/react-query";
import type { ApprovalSummary } from "../types";
import { toErrorMessage } from "./chat-surface";
import type { ZebraApiClient } from "./zebra-api";
import { decideActiveApproval } from "@zebra-agent/task-ui";

export function useActiveApproval(
  api: ZebraApiClient,
  sessionId: string | undefined,
  sessionStatus: string | undefined,
  onChanged: () => Promise<unknown>,
) {
  const enabled = Boolean(sessionId && sessionStatus === "waiting_approval");
  const queue = useQuery({
    queryKey: ["active-approval", sessionId],
    queryFn: api.approvals,
    enabled,
    refetchInterval: enabled ? 2_000 : false,
  });
  const summary = queue.data?.approvals.find((item) => item.session_id === sessionId);
  const detail = useQuery({
    queryKey: ["active-approval-detail", summary?.approval_id],
    queryFn: () => api.approval(summary!.approval_id),
    enabled: Boolean(summary),
  });
  const decide = useMutation({
    mutationFn: async ({ approval, decision }: { approval: ApprovalSummary; decision: "approve" | "reject" }) => {
      return decideActiveApproval(api, approval, decision);
    },
    onSuccess: async () => {
      await Promise.all([queue.refetch(), detail.refetch(), onChanged()]);
    },
  });
  return {
    approval: detail.data ?? summary,
    busy: queue.isLoading || detail.isLoading || decide.isPending,
    errorText: queue.error || detail.error || decide.error ? toErrorMessage(queue.error ?? detail.error ?? decide.error) : null,
    approve: (approval: ApprovalSummary) => decide.mutateAsync({ approval, decision: "approve" }),
    reject: (approval: ApprovalSummary) => decide.mutateAsync({ approval, decision: "reject" }),
  };
}
