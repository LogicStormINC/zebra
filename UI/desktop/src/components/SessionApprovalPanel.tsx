import { Descriptions } from "antd";
import { ApprovalCard } from "@zebra-agent/task-ui/react";
import type { TaskApproval } from "@zebra-agent/task-ui";
import type { ApprovalSummary } from "../types";

interface SessionApprovalPanelProps {
  approval: ApprovalSummary | undefined;
  busy: boolean;
  errorText: string | null;
  onApprove: (approval: ApprovalSummary) => Promise<unknown>;
  onReject: (approval: ApprovalSummary) => Promise<unknown>;
}

const toTaskApproval = (approval: ApprovalSummary): TaskApproval => ({
  approval_context: approval.approval_context,
  state: "pending",
});

export function SessionApprovalPanel({ approval, busy, errorText, onApprove, onReject }: SessionApprovalPanelProps) {
  const taskApproval = approval ? toTaskApproval(approval) : undefined;
  return (
    <ApprovalCard
      approval={taskApproval}
      busy={busy}
      errorText={errorText}
      onApprove={() => approval ? onApprove(approval) : Promise.resolve()}
      onReject={() => approval ? onReject(approval) : Promise.resolve()}
      renderExtraDetails={(current) => {
        const context = current.approval_context;
        const searchQuery = context?.tool_name === "web.search" && typeof approval?.approval_context?.arguments?.query === "string"
          ? approval.approval_context.arguments.query
          : null;
        const searchLimit = context?.tool_name === "web.search" && typeof approval?.approval_context?.arguments?.limit === "number"
          ? approval.approval_context.arguments.limit
          : null;
        return (
          <>
            {searchQuery !== null ? <Descriptions.Item label="查询">{searchQuery}</Descriptions.Item> : null}
            {searchLimit !== null ? <Descriptions.Item label="结果上限">{searchLimit}</Descriptions.Item> : null}
          </>
        );
      }}
    />
  );
}
