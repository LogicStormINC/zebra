import { useEffect, useMemo, useState } from "react";
import { Button, Card, List, Space, Spin, Statistic, Tag, Typography, Alert, Radio } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { createStyles } from "antd-style";
import type { ZebraApiClient } from "../lib/zebra-api";
import { buildMemoryScopeOptions, useMemoryScopeSurface } from "../lib/use-memory-scope-surface";
import type { MemoryScopeKind } from "../types";

const useStyle = createStyles(({ css }) => ({
  secondaryText: css`
    margin-bottom: 0;
    color: rgba(255, 255, 255, 0.58) !important;
  `,
  loadingArea: css`
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: calc(var(--zebra-space-xl) + var(--zebra-space-xl));
  `,
  titleBlock: css`
    margin-top: var(--zebra-space-2xs);
  `,
}));

interface ScopeMemoryCardProps {
  api: ZebraApiClient;
  sessionId: string;
  userId: string;
  tenantId: string;
}

export function ScopeMemoryCard({
  api,
  sessionId,
  userId,
  tenantId,
}: ScopeMemoryCardProps) {
  const scopes = useMemo(
    () => buildMemoryScopeOptions(sessionId, userId, tenantId),
    [sessionId, userId, tenantId],
  );
  const [selectedScope, setSelectedScope] = useState<MemoryScopeKind>("session");

  useEffect(() => {
    if (!scopes.length) {
      setSelectedScope("session");
      return;
    }
    if (!scopes.some((scope) => scope.kind === selectedScope)) {
      setSelectedScope(scopes[0].kind);
    }
  }, [scopes, selectedScope]);

  const surface = useMemoryScopeSurface(api, sessionId, userId, tenantId, selectedScope);
  const { styles } = useStyle();

  return (
    <Card
      title="Scope Memory Snapshot"
      extra={
        <Button icon={<ReloadOutlined />} onClick={() => void surface.refresh()} disabled={surface.loading}>
          Refresh
        </Button>
      }
    >
      <Space direction="vertical" size="large" className="w-full">
        <Typography.Paragraph className={styles.secondaryText}>
          Read the active scope inventory and queue summary before doing queue-sweep or bulk-review operations.
        </Typography.Paragraph>
        {surface.errorText ? (
          <Alert type="warning" showIcon message="Scope memory read failed" description={surface.errorText} />
        ) : null}
        {!surface.scope ? (
          <Alert
            type="info"
            showIcon
            message="No scope selected"
            description="Set a session id, user id, or tenant id in the operator config first."
          />
        ) : null}
        {scopes.length ? (
              <div>
                <Typography.Text strong>Read Scope</Typography.Text>
                <Radio.Group
                  className={styles.titleBlock}
                  optionType="button"
                  buttonStyle="solid"
                  value={selectedScope}
              onChange={(event) => setSelectedScope(event.target.value)}
              options={scopes.map((scope) => ({
                label: `${scope.label}: ${scope.targetId}`,
                value: scope.kind,
              }))}
            />
          </div>
        ) : null}
        {surface.loading ? (
          <div className={styles.loadingArea}>
            <Spin />
          </div>
        ) : null}
        {surface.scope && !surface.loading ? (
          <>
            <Space size="large" wrap>
              <Statistic title="Pending queue" value={surface.queueSummary?.pending_count ?? 0} />
              <Statistic title="Inventory size" value={surface.memories.length} />
            </Space>
            <Space wrap>
              <Tag color="geekblue">{surface.scope.kind}</Tag>
              <Tag>{surface.scope.targetId}</Tag>
              <Tag color={surface.queueSummary?.queue_status === "pending" ? "orange" : "green"}>
                {surface.queueSummary?.queue_status ?? "unknown"}
              </Tag>
              {surface.queueSummary?.latest_updated_at ? <Tag>{surface.queueSummary.latest_updated_at}</Tag> : null}
            </Space>
            <List
              dataSource={surface.memories}
              locale={{ emptyText: "No memories recorded for this scope yet." }}
              renderItem={(memory) => (
                <List.Item>
                  <Space direction="vertical" size={4} className="w-full">
                    <Space wrap>
                      <Tag color="blue">{memory.memory_type}</Tag>
                      <Tag>{memory.status}</Tag>
                      <Tag>{memory.visibility}</Tag>
                    </Space>
                    <Typography.Text>{memory.text}</Typography.Text>
                    <Typography.Text type="secondary">
                      {memory.source?.kind ?? "unknown"} · {memory.updated_at}
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </>
        ) : null}
      </Space>
    </Card>
  );
}
