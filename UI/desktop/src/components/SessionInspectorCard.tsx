import { Bubble, Prompts } from "@ant-design/x";
import { Alert, Button, Card, Descriptions, List, Modal, Space, Spin, Statistic, Tabs, Tag, Typography } from "antd";
import { createStyles } from "antd-style";
import type {
  ArtifactSummary,
  DeliveryAuditRecord,
  MemoryOverviewResponse,
  SessionArtifactsResponse,
  SessionDeliveryAuditResponse,
  SessionDiffResponse,
  SessionEvent,
  SessionMemoryResponse,
  SessionSummary,
} from "../types";

const useStyle = createStyles(({ css }) => ({
  loadingArea: css`
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: calc(var(--zebra-space-xxl) + var(--zebra-space-xxl));
  `,
  scopeList: css`
    min-width: min(100%, var(--zebra-sidebar-width-max));
    flex: 1;
  `,
  eventPayload: css`
    margin-top: var(--zebra-space-2xs);
    margin-bottom: 0;
    overflow-x: auto;
    white-space: pre-wrap;
    font-size: var(--zebra-font-size-2xs);
    line-height: var(--zebra-line-height-relaxed);
    color: rgba(255, 255, 255, 0.6);
  `,
  bubbleList: css`
    border-radius: var(--zebra-radius-card);
    background: var(--zebra-surface-background);
    padding: var(--zebra-space-md);
  `,
  preBlock: css`
    margin: 0;
    overflow-x: auto;
    white-space: pre-wrap;
    border-radius: var(--zebra-radius-card);
    padding: var(--zebra-space-md);
    font-size: var(--zebra-font-size-2xs);
    line-height: var(--zebra-line-height-relaxed);
    color: rgba(255, 255, 255, 0.86);
    background: var(--zebra-surface-background);
  `,
  preBlockDark: css`
    margin: 0;
    overflow-x: auto;
    white-space: pre-wrap;
    border-radius: var(--zebra-radius-card);
    padding: var(--zebra-space-md);
    font-size: var(--zebra-font-size-2xs);
    line-height: var(--zebra-line-height-relaxed);
    color: rgba(241, 245, 249, 0.95);
    background: #101010;
  `,
  preBlockSmall: css`
    margin: 0;
    overflow-x: auto;
    white-space: pre-wrap;
    border-radius: var(--zebra-radius-soft);
    padding: var(--zebra-space-sm);
    font-size: var(--zebra-font-size-2xs);
    line-height: var(--zebra-line-height-relaxed);
    color: rgba(255, 255, 255, 0.86);
    background: var(--zebra-surface-background);
  `,
  secondaryText: css`
    margin-bottom: 0;
    color: rgba(255, 255, 255, 0.58) !important;
  `,
  artifactContent: css`
    margin: 0;
    overflow: auto;
    white-space: pre-wrap;
    border-radius: var(--zebra-radius-card);
    padding: var(--zebra-space-md);
    font-size: var(--zebra-font-size-2xs);
    line-height: var(--zebra-line-height-relaxed);
    color: rgba(255, 255, 255, 0.88);
    background: var(--zebra-surface-background);
    max-height: calc(var(--zebra-space-xxl) * 8);
  `,
}));

interface SessionInspectorCardProps {
  session: SessionSummary | undefined;
  stream: SessionEvent[] | undefined;
  memory: SessionMemoryResponse | undefined;
  overview: MemoryOverviewResponse | undefined;
  diff: SessionDiffResponse | undefined;
  artifacts: SessionArtifactsResponse | undefined;
  deliveryAudit: SessionDeliveryAuditResponse | undefined;
  isLoading: boolean;
  errorText: string | null;
  selectedArtifact: ArtifactSummary | null;
  artifactContentPreview: string | null;
  onInspectArtifact: (artifactId: string) => void;
  onReadArtifact: (artifactId: string) => void;
  onPruneArtifact: (artifactId: string) => void;
  onCloseArtifactModal: () => void;
  onConfirmMemory: (memoryId: string) => void;
  onExpireMemory: (memoryId: string) => void;
}

function bubbleItems(events: SessionEvent[] | undefined, eventPayloadClass: string) {
  return (events ?? []).map((event) => ({
    key: event.event_id,
    role: event.actor === "assistant" ? "assistant" : "user",
    content: `${event.event_type}\n${JSON.stringify(event.payload, null, 2)}`,
    messageRender: () => (
      <div>
        <Typography.Text strong>{event.event_type}</Typography.Text>
        <pre className={eventPayloadClass}>{JSON.stringify(event.payload, null, 2)}</pre>
      </div>
    ),
  }));
}

export function SessionInspectorCard({
  session,
  stream,
  memory,
  overview,
  diff,
  artifacts,
  deliveryAudit,
  isLoading,
  errorText,
  selectedArtifact,
  artifactContentPreview,
  onInspectArtifact,
  onReadArtifact,
  onPruneArtifact,
  onCloseArtifactModal,
  onConfirmMemory,
  onExpireMemory,
}: SessionInspectorCardProps) {
  const { styles } = useStyle();

  return (
    <Card title="Session Inspector">
      {errorText ? <Alert type="warning" showIcon message="Session unavailable" description={errorText} /> : null}
      {isLoading ? (
        <div className={styles.loadingArea}>
          <Spin />
        </div>
      ) : null}
      {!isLoading && !session ? (
        <Alert type="info" showIcon message="No active session" description="Create a session or paste an existing session id." />
      ) : null}
      {!isLoading && session ? (
        <Space direction="vertical" size="large" className="w-full">
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="Session">{session.session_id}</Descriptions.Item>
            <Descriptions.Item label="Status">
              <Tag color={session.status === "waiting_approval" ? "gold" : "blue"}>{session.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Title">{session.title}</Descriptions.Item>
            <Descriptions.Item label="Sequence">{session.current_sequence}</Descriptions.Item>
            <Descriptions.Item label="Workspace" span={2}>
              {session.workspace?.workspace_root ?? "Unavailable"}
            </Descriptions.Item>
          </Descriptions>
          <Prompts
            title="Quick read surfaces"
            items={[
              { key: "events", label: "Stream", description: `${stream?.length ?? 0} events` },
              { key: "memory", label: "Repo memory", description: `${memory?.memories.length ?? 0} records` },
              { key: "overview", label: "Overview", description: `${overview?.scope_count ?? 0} scopes` },
            ]}
            wrap
          />
          <Tabs
            items={[
              {
                key: "overview",
                label: "Overview",
                children: (
                  <Space size="large" wrap className="w-full">
                    <Statistic title="Pending memories" value={overview?.total_pending_count ?? 0} />
                    <Statistic title="Scopes" value={overview?.scope_count ?? 0} />
                    <Statistic title="Repo memories" value={memory?.memories.length ?? 0} />
                    <List
                      className={styles.scopeList}
                      dataSource={overview?.scopes ?? []}
                      renderItem={(scope) => (
                        <List.Item>
                          <Space direction="vertical" size={2}>
                            <Space wrap>
                              <Tag color="geekblue">{scope.scope_kind}</Tag>
                              <Tag>{scope.queue_status}</Tag>
                            </Space>
                            <Typography.Text>{scope.scope_id}</Typography.Text>
                            <Typography.Text type="secondary">
                              pending={scope.pending_count}
                              {scope.latest_updated_at ? ` · latest=${scope.latest_updated_at}` : ""}
                            </Typography.Text>
                          </Space>
                        </List.Item>
                      )}
                    />
                  </Space>
                ),
              },
              {
                key: "events",
                label: "Event Stream",
                children: (
                  <Bubble.List
                    items={bubbleItems(stream, styles.eventPayload)}
                    role={{
                      assistant: { placement: "start" },
                      user: { placement: "end" },
                    }}
                    className={styles.bubbleList}
                  />
                ),
              },
              {
                key: "memory",
                label: "Repo Memory",
                children: (
                  <List
                    dataSource={memory?.memories ?? []}
                    locale={{ emptyText: "No repo-scoped memories yet." }}
                    renderItem={(record) => (
                      <List.Item
                        actions={
                          record.status === "candidate"
                            ? [
                                <Button key="confirm" type="link" onClick={() => onConfirmMemory(record.memory_id)}>
                                  Confirm
                                </Button>,
                                <Button key="expire" type="link" danger onClick={() => onExpireMemory(record.memory_id)}>
                                  Expire
                                </Button>,
                              ]
                            : undefined
                        }
                      >
                        <Space direction="vertical" size={4}>
                          <Space wrap>
                            <Tag color="blue">{record.memory_type}</Tag>
                            <Tag>{record.status}</Tag>
                            <Tag>{record.visibility}</Tag>
                          </Space>
                          <Typography.Text>{record.text}</Typography.Text>
                          <Typography.Text type="secondary">
                            {record.source?.kind ?? "unknown"} · {record.updated_at}
                          </Typography.Text>
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              },
              {
                key: "diff",
                label: "Workspace Diff",
                children: diff ? (
                  <Space direction="vertical" size="middle" className="w-full">
                    <Space wrap>
                      <Tag color={diff.clean ? "green" : "orange"}>{diff.clean ? "clean" : "dirty"}</Tag>
                      <Typography.Text type="secondary">{diff.workspace}</Typography.Text>
                    </Space>
                    <Typography.Title level={5}>Git Status</Typography.Title>
                    <pre className={styles.preBlock}>{diff.git_status || "(empty)"}</pre>
                    <Typography.Title level={5}>Diff</Typography.Title>
                    <pre className={styles.preBlockDark}>{diff.diff || "(empty)"}</pre>
                  </Space>
                ) : (
                  <Alert type="info" showIcon message="Diff not loaded" />
                ),
              },
              {
                key: "artifacts",
                label: "Artifacts",
                children: (
                  <List
                    dataSource={artifacts?.artifacts ?? []}
                    locale={{ emptyText: "No session artifacts yet." }}
                    renderItem={(artifact) => (
                      <List.Item
                        actions={[
                          <a key="inspect" onClick={() => onInspectArtifact(artifact.artifact_id)}>
                            Inspect
                          </a>,
                          <a
                            key="read"
                            onClick={() => onReadArtifact(artifact.artifact_id)}
                          >
                            Read
                          </a>,
                          <Button
                            key="prune"
                            type="link"
                            danger
                            onClick={() => onPruneArtifact(artifact.artifact_id)}
                          >
                            Prune
                          </Button>,
                        ]}
                      >
                        <Space direction="vertical" size={4} className="w-full">
                          <Space wrap>
                            <Tag color="blue">{artifact.source}</Tag>
                            <Tag>{artifact.kind}</Tag>
                            <Tag color={artifact.access.allowed ? "green" : "red"}>{artifact.access.class}</Tag>
                            <Tag color="purple">{artifact.retrieval.status}</Tag>
                          </Space>
                          <Typography.Text strong>{artifact.label}</Typography.Text>
                          <Typography.Paragraph className={styles.secondaryText}>
                            {artifact.preview ?? "(no preview)"}
                          </Typography.Paragraph>
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              },
              {
                key: "audit",
                label: "Delivery Audit",
                children: (
                  <List
                    dataSource={deliveryAudit?.delivery_audit ?? []}
                    locale={{ emptyText: "No delivery audit records yet." }}
                    renderItem={(record: DeliveryAuditRecord) => (
                      <List.Item>
                        <Space direction="vertical" size={4}>
                          <Space wrap>
                            <Tag color="geekblue">{record.action}</Tag>
                            <Tag>{record.status}</Tag>
                            <Tag>{record.status_code}</Tag>
                          </Space>
                          <Typography.Text type="secondary">
                            {record.created_at}
                          </Typography.Text>
                          <pre className={styles.preBlockSmall}>
                            {JSON.stringify(record.result_metadata, null, 2)}
                          </pre>
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              },
            ]}
          />
          <Modal
            open={selectedArtifact !== null}
            onCancel={onCloseArtifactModal}
            footer={null}
            width={920}
            title={selectedArtifact?.artifact_id ?? "Artifact"}
          >
            {selectedArtifact ? (
              <Space direction="vertical" size="middle" className="w-full">
                <Space wrap>
                  <Tag color="blue">{selectedArtifact.source}</Tag>
                  <Tag>{selectedArtifact.kind}</Tag>
                  <Tag color={selectedArtifact.access.allowed ? "green" : "red"}>
                    {selectedArtifact.access.class}
                  </Tag>
                  <Tag color="purple">{selectedArtifact.retrieval.status}</Tag>
                </Space>
                <Typography.Title level={5}>Preview</Typography.Title>
                <pre className={styles.preBlock}>{selectedArtifact.preview ?? "(no preview)"}</pre>
                <Typography.Title level={5}>Metadata</Typography.Title>
                <pre className={styles.preBlockDark}>{JSON.stringify(selectedArtifact.metadata, null, 2)}</pre>
                {artifactContentPreview ? (
                  <>
                    <Typography.Title level={5}>Content</Typography.Title>
                    <pre className={styles.artifactContent}>
                      {artifactContentPreview}
                    </pre>
                  </>
                ) : null}
              </Space>
            ) : null}
          </Modal>
        </Space>
      ) : null}
    </Card>
  );
}
