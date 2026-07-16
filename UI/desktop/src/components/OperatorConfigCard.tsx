import { DatabaseOutlined, ReloadOutlined } from "@ant-design/icons";
import { Button, Divider, Form, Input, Space, Tag, Typography } from "antd";
import { createStyles } from "antd-style";
import locale from "../_utils/local";
import { projectMcpCapabilities } from "../lib/mcp-capabilities";
import type { RuntimeConnectionStatus } from "../lib/runtime-connection";
import type { McpCapabilitiesResponse, OperatorConfig } from "../types";

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
  capabilityGroup: css`
    width: 100%;
    padding: 12px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.025);
  `,
  fieldText: css`
    color: rgba(255, 255, 255, 0.46) !important;
  `,
}));

interface OperatorConfigCardProps {
  config: OperatorConfig;
  mcpCapabilities: McpCapabilitiesResponse | undefined;
  mcpCapabilitiesBusy: boolean;
  mcpCapabilitiesError: string | null;
  onChange: (patch: Partial<OperatorConfig>) => void;
  onRetry: () => void;
  onRetryMcpCapabilities: () => void;
  onReset: () => void;
  runtimeStatus: RuntimeConnectionStatus;
}

export function OperatorConfigCard({
  config,
  mcpCapabilities,
  mcpCapabilitiesBusy,
  mcpCapabilitiesError,
  onChange,
  onRetry,
  onRetryMcpCapabilities,
  onReset,
  runtimeStatus,
}: OperatorConfigCardProps) {
  const { styles } = useStyle();
  const mcpView = projectMcpCapabilities(mcpCapabilities, mcpCapabilitiesBusy, mcpCapabilitiesError);
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
      <Divider />
      <div className={styles.statusRow}>
        <Typography.Text>MCP 能力</Typography.Text>
        <Tag color={mcpView.color}>{mcpView.label}</Tag>
      </div>
      <Typography.Paragraph className={styles.secondaryText}>{mcpView.summary}</Typography.Paragraph>
      {mcpCapabilities?.status === "available" ? (
        <Space direction="vertical" size="small" className="w-full">
          {mcpCapabilities.servers.map((server) => (
            <Space key={server.name} direction="vertical" size={6} className={styles.capabilityGroup}>
              <Typography.Text strong>{server.name}</Typography.Text>
              {server.tools.map((tool) => (
                <div key={tool.name}>
                  <Typography.Text>{tool.name}</Typography.Text>
                  {tool.description ? (
                    <Typography.Paragraph className={styles.secondaryText}>{tool.description}</Typography.Paragraph>
                  ) : null}
                  <Typography.Text className={styles.fieldText}>
                    输入字段：{tool.input_fields.length ? tool.input_fields.join("、") : "无"}
                  </Typography.Text>
                </div>
              ))}
            </Space>
          ))}
        </Space>
      ) : null}
      <Button
        icon={<ReloadOutlined />}
        loading={mcpCapabilitiesBusy}
        disabled={runtimeStatus !== "connected"}
        onClick={onRetryMcpCapabilities}
      >
        刷新能力清单
      </Button>
    </Space>
  );
}
