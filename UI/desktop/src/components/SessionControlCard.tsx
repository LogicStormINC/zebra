import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Descriptions, Input, Space, Tag, Typography } from "antd";
import { createStyles } from "antd-style";
import { useState } from "react";
import type { ApprovalSummary, SessionSummary } from "../types";

const useStyle = createStyles(({ css }) => ({
  secondaryText: css`
    margin-bottom: 0 !important;
    color: rgba(255, 255, 255, 0.58) !important;
  `,
}));

interface SessionControlCardProps {
  session: SessionSummary | undefined;
  approvalDetail: ApprovalSummary | undefined;
  busy: boolean;
  errorText: string | null;
  onApprove: (payload: { operator?: string; reason?: string }) => Promise<unknown>;
  onReject: (payload: { operator?: string; reason?: string }) => Promise<unknown>;
  onSuspend: () => Promise<unknown>;
  onCancel: () => Promise<unknown>;
  onResume: () => Promise<unknown>;
}

export function SessionControlCard({
  session,
  approvalDetail,
  busy,
  errorText,
  onApprove,
  onReject,
  onSuspend,
  onCancel,
  onResume,
}: SessionControlCardProps) {
  const [operator, setOperator] = useState("desktop-operator");
  const [reason, setReason] = useState("");
  const { styles } = useStyle();

  const approvalPayload = {
    operator: operator.trim() || "desktop-operator",
    reason: reason.trim() || undefined,
  };

  return (
    <Card title="Session Controls">
      <Space direction="vertical" size="middle" className="w-full">
        {errorText ? <Alert type="warning" showIcon message="Latest control error" description={errorText} /> : null}
        {!session ? (
          <Alert type="info" showIcon message="No active session" description="Select or create a session first." />
        ) : (
          <>
            <Space wrap>
              <Tag color="blue">{session.status}</Tag>
              <Tag>{session.current_sequence}</Tag>
              {session.workspace?.status ? <Tag color="purple">{session.workspace.status}</Tag> : null}
            </Space>
            {approvalDetail ? (
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label="Approval ID">{approvalDetail.approval_id}</Descriptions.Item>
                <Descriptions.Item label="Reason">
                  {approvalDetail.approval_context?.reason ?? "Unavailable"}
                </Descriptions.Item>
                <Descriptions.Item label="Route">
                  {approvalDetail.approval_context?.route ?? "Unavailable"}
                </Descriptions.Item>
                <Descriptions.Item label="Target">
                  {approvalDetail.approval_context?.target ?? "Unavailable"}
                </Descriptions.Item>
                <Descriptions.Item label="Policy">
                  {approvalDetail.approval_context?.policy_profile ?? "Unavailable"}
                </Descriptions.Item>
                <Descriptions.Item label="Scope">
                  {approvalDetail.approval_context?.scope?.join(", ") || "Unavailable"}
                </Descriptions.Item>
              </Descriptions>
            ) : null}
            <Input
              value={operator}
              onChange={(event) => setOperator(event.target.value)}
              placeholder="Operator name"
            />
            <Input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Optional reason override"
            />
            <Space wrap>
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                disabled={busy || session.status !== "waiting_approval"}
                onClick={() => void onApprove(approvalPayload)}
              >
                Approve
              </Button>
              <Button
                danger
                icon={<CloseCircleOutlined />}
                disabled={busy || session.status !== "waiting_approval"}
                onClick={() => void onReject(approvalPayload)}
              >
                Reject
              </Button>
              <Button
                icon={<PauseCircleOutlined />}
                disabled={busy}
                onClick={() => void onSuspend()}
              >
                Suspend
              </Button>
              <Button
                icon={<PlayCircleOutlined />}
                disabled={busy}
                onClick={() => void onResume()}
              >
                Resume
              </Button>
              <Button
                icon={<StopOutlined />}
                disabled={busy}
                onClick={() => void onCancel()}
              >
                Cancel
              </Button>
            </Space>
            <Typography.Paragraph className={styles.secondaryText}>
              当前用最小控制面直接对接审批与会话控制接口。后续如果补流式状态更新，再把这些动作迁到更细的工作流面板。
            </Typography.Paragraph>
          </>
        )}
      </Space>
    </Card>
  );
}
