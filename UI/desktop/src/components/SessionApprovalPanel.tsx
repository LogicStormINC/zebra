import { CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { Alert, Button, Descriptions, Space } from "antd";
import type { ApprovalSummary } from "../types";

interface SessionApprovalPanelProps {
  approval: ApprovalSummary | undefined;
  busy: boolean;
  errorText: string | null;
  onApprove: (approval: ApprovalSummary) => Promise<unknown>;
  onReject: (approval: ApprovalSummary) => Promise<unknown>;
}

export function SessionApprovalPanel({ approval, busy, errorText, onApprove, onReject }: SessionApprovalPanelProps) {
  if (!approval && !errorText) return null;
  const context = approval?.approval_context;
  const searchQuery = context?.tool_name === "web.search" && typeof context.arguments?.query === "string"
    ? context.arguments.query
    : null;
  const searchLimit = context?.tool_name === "web.search" && typeof context.arguments?.limit === "number"
    ? context.arguments.limit
    : null;
  return (
    <section aria-label="需要人工确认">
      {errorText ? <Alert showIcon type="warning" message="审批信息读取失败" description={errorText} /> : null}
      {approval ? (
        <Space direction="vertical" size="middle" className="w-full">
          <Alert showIcon type="warning" message="Agent 需要人工确认" description={approval.approval_context?.reason} />
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="操作">{context?.tool_name ?? "未知"}</Descriptions.Item>
            <Descriptions.Item label="出口">{context?.route ?? "本地"}</Descriptions.Item>
            <Descriptions.Item label="目标">{approval.approval_context?.target ?? "未提供"}</Descriptions.Item>
            {searchQuery ? <Descriptions.Item label="查询">{searchQuery}</Descriptions.Item> : null}
            {searchLimit !== null ? <Descriptions.Item label="结果上限">{searchLimit}</Descriptions.Item> : null}
            <Descriptions.Item label="权限策略">{approval.approval_context?.policy_profile ?? "未提供"}</Descriptions.Item>
            <Descriptions.Item label="范围">{approval.approval_context?.scope?.join(", ") || "未提供"}</Descriptions.Item>
          </Descriptions>
          <Space>
            <Button type="primary" icon={<CheckCircleOutlined />} loading={busy} onClick={() => void onApprove(approval)}>批准</Button>
            <Button danger icon={<CloseCircleOutlined />} disabled={busy} onClick={() => void onReject(approval)}>拒绝</Button>
          </Space>
        </Space>
      ) : null}
    </section>
  );
}
