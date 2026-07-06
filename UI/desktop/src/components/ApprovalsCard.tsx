import { SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, Card, List, Space, Tag, Typography } from "antd";
import type { ApprovalSummary } from "../types";

interface ApprovalsCardProps {
  approvals: ApprovalSummary[] | undefined;
  isLoading: boolean;
  errorText: string | null;
  onSelect: (approvalId: string, sessionId: string) => void;
}

export function ApprovalsCard({ approvals, isLoading, errorText, onSelect }: ApprovalsCardProps) {
  return (
    <Card title="Approval Inbox" extra={<SafetyCertificateOutlined />}>
      <Space direction="vertical" size="middle" className="w-full">
        {errorText ? <Alert type="warning" showIcon message="Approvals unavailable" description={errorText} /> : null}
        <List
          loading={isLoading}
          dataSource={approvals ?? []}
          locale={{ emptyText: "No waiting approvals." }}
          renderItem={(approval) => (
            <List.Item
              className="cursor-pointer !items-start"
              onClick={() => onSelect(approval.approval_id, approval.session_id)}
            >
              <Space direction="vertical" size={6} className="w-full">
                <Space wrap>
                  <Tag color="gold">{approval.status}</Tag>
                  <Tag>{approval.current_sequence}</Tag>
                  {approval.approval_context?.route ? <Tag color="geekblue">{approval.approval_context.route}</Tag> : null}
                  {approval.approval_context?.target ? <Tag color="purple">{approval.approval_context.target}</Tag> : null}
                </Space>
                <Typography.Text strong>{approval.title}</Typography.Text>
                <Typography.Text type="secondary">{approval.session_id}</Typography.Text>
                {approval.approval_context?.reason ? (
                  <Typography.Paragraph className="!mb-0 !text-slate-600">
                    {approval.approval_context.reason}
                  </Typography.Paragraph>
                ) : null}
              </Space>
            </List.Item>
          )}
        />
      </Space>
    </Card>
  );
}
