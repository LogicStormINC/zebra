export type ApprovalDecisionApi = {
  approve: (approvalId: string, payload: { operator: string }) => Promise<unknown>;
  reject: (approvalId: string, payload: { operator: string }) => Promise<unknown>;
  resume: (sessionId: string) => Promise<unknown>;
};

export type ApprovalIdentity = {
  approval_id: string;
  session_id: string;
};

export async function decideActiveApproval(
  api: ApprovalDecisionApi,
  approval: ApprovalIdentity,
  decision: "approve" | "reject",
) {
  const result = await api[decision](approval.approval_id, { operator: "desktop-operator" });
  if (decision === "approve") {
    await api.resume(approval.session_id);
  }
  return result;
}
