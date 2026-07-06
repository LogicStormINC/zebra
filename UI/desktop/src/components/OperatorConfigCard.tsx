import { DatabaseOutlined, ReloadOutlined } from "@ant-design/icons";
import { Prompts } from "@ant-design/x";
import { Button, Card, Form, Input, Space, Typography } from "antd";
import type { OperatorConfig } from "../types";

const promptItems = [
  {
    key: "local-api",
    label: "本地 API",
    description: "127.0.0.1:8000",
  },
  {
    key: "demo-scope",
    label: "示例 Scope",
    description: "填充 user 和 tenant 标识",
  },
  {
    key: "clear-auth",
    label: "清空 Token",
    description: "只保留匿名读路径",
  },
];

interface OperatorConfigCardProps {
  config: OperatorConfig;
  onChange: (patch: Partial<OperatorConfig>) => void;
  onReset: () => void;
}

export function OperatorConfigCard({ config, onChange, onReset }: OperatorConfigCardProps) {
  return (
    <Card
      title="Operator Config"
      extra={
        <Button icon={<ReloadOutlined />} onClick={onReset}>
          Reset
        </Button>
      }
    >
      <Space direction="vertical" size="large" className="w-full">
        <Typography.Paragraph className="!mb-0 !text-slate-600">
          UI 直接对接本地 Zebra Agent HTTP API。`/health` 不需要鉴权，其它读写路径在你配置
          `ZEBRA_API_AUTH_TOKEN` 后通常需要 `Bearer token`。
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="API Base URL">
            <Input
              prefix={<DatabaseOutlined />}
              value={config.apiBaseUrl}
              onChange={(event) => onChange({ apiBaseUrl: event.target.value })}
            />
          </Form.Item>
          <Form.Item label="Bearer Token">
            <Input.Password
              value={config.authToken}
              onChange={(event) => onChange({ authToken: event.target.value })}
              placeholder="Optional"
            />
          </Form.Item>
          <Form.Item label="Current Session ID">
            <Input
              value={config.sessionId}
              onChange={(event) => onChange({ sessionId: event.target.value })}
              placeholder="Paste an existing session id or create one below"
            />
          </Form.Item>
          <Form.Item label="User Scope ID">
            <Input
              value={config.userId}
              onChange={(event) => onChange({ userId: event.target.value })}
              placeholder="Optional"
            />
          </Form.Item>
          <Form.Item label="Tenant Scope ID">
            <Input
              value={config.tenantId}
              onChange={(event) => onChange({ tenantId: event.target.value })}
              placeholder="Optional"
            />
          </Form.Item>
        </Form>
        <Prompts
          title="Quick presets"
          items={promptItems}
          wrap
          onItemClick={({ data }) => {
            if (data.key === "local-api") {
              onChange({ apiBaseUrl: "http://127.0.0.1:8000" });
            }
            if (data.key === "demo-scope") {
              onChange({ userId: "user-1", tenantId: "tenant-1" });
            }
            if (data.key === "clear-auth") {
              onChange({ authToken: "" });
            }
          }}
        />
      </Space>
    </Card>
  );
}
