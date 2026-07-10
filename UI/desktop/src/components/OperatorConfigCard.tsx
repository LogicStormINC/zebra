import { DatabaseOutlined, ReloadOutlined } from "@ant-design/icons";
import { Button, Form, Input, Space, Tag, Typography } from "antd";
import { createStyles } from "antd-style";
import locale from "../_utils/local";
import type { RuntimeConnectionStatus } from "../lib/runtime-connection";
import type { OperatorConfig } from "../types";

const useStyle = createStyles(({ css }) => ({
  secondaryText: css`
    margin-bottom: 0;
    color: rgba(255, 255, 255, 0.58) !important;
  `,
  statusRow: css`
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
  `,
}));

interface OperatorConfigCardProps {
  config: OperatorConfig;
  onChange: (patch: Partial<OperatorConfig>) => void;
  onRetry: () => void;
  onReset: () => void;
  runtimeStatus: RuntimeConnectionStatus;
}

export function OperatorConfigCard({ config, onChange, onRetry, onReset, runtimeStatus }: OperatorConfigCardProps) {
  const { styles } = useStyle();
  const statusLabel =
    runtimeStatus === "connected"
      ? locale.runtimeConnected
      : runtimeStatus === "checking"
        ? locale.runtimeChecking
        : locale.runtimeDisconnected;
  return (
    <Space direction="vertical" size="large" className="w-full">
      <div className={styles.statusRow}>
        <Typography.Text>连接状态</Typography.Text>
        <Tag color={runtimeStatus === "connected" ? "green" : runtimeStatus === "checking" ? "gold" : "red"}>
          {statusLabel}
        </Tag>
      </div>
      <Typography.Paragraph className={styles.secondaryText}>
        桌面端直接连接本地 Zebra Agent HTTP API。健康检查无需鉴权，其余接口在服务端启用
        `ZEBRA_API_AUTH_TOKEN` 后需要 Bearer Token。
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
      </Form>
      <Space>
        <Button icon={<ReloadOutlined />} loading={runtimeStatus === "checking"} onClick={onRetry}>
          重新检查
        </Button>
        <Button onClick={onReset}>恢复默认配置</Button>
      </Space>
    </Space>
  );
}
