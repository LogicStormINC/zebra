import { useMemo } from "react";
import { Alert, Card, Col, Layout, Row, Space, Statistic, Tag, Typography } from "antd";
import { DesktopOutlined } from "@ant-design/icons";
import { ApprovalsCard } from "./components/ApprovalsCard";
import { MemoryQueueCard } from "./components/MemoryQueueCard";
import { MemoryGovernanceCard } from "./components/MemoryGovernanceCard";
import { OperatorConfigCard } from "./components/OperatorConfigCard";
import { SessionComposerCard } from "./components/SessionComposerCard";
import { SessionControlCard } from "./components/SessionControlCard";
import { SessionDeliveryCard } from "./components/SessionDeliveryCard";
import { SessionInspectorCard } from "./components/SessionInspectorCard";
import { SessionMessageCard } from "./components/SessionMessageCard";
import { ScopeMemoryCard } from "./components/ScopeMemoryCard";
import { useOperatorConfig } from "./lib/operator-config";
import { formatOperatorError, useOperatorWorkbench } from "./lib/use-operator-workbench";

const { Header, Content } = Layout;
const { Title, Paragraph, Text } = Typography;

export default function App() {
  const { config, patchConfig, resetConfig } = useOperatorConfig();
  const workbench = useOperatorWorkbench(config, patchConfig);
  const {
    queries: {
      healthQuery,
      approvalsQuery,
      approvalDetailQuery,
      sessionQuery,
      streamQuery,
      diffQuery,
      memoryQuery,
      artifactsQuery,
      deliveryAuditQuery,
      overviewQuery,
    },
    actions,
    busy,
    errorText,
    selectedArtifact,
    artifactContentPreview,
  } = workbench;
  const now = useMemo(
    () => new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date()),
    [],
  );

  return (
    <Layout className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(22,119,255,0.14),_transparent_28%),linear-gradient(180deg,_#f6f8fb_0%,_#eef3f8_100%)]">
      <Header className="flex items-center justify-between border-b border-slate-200/70 bg-white/70 px-6 backdrop-blur">
        <Space size="middle">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-950 text-white">
            <DesktopOutlined />
          </div>
          <div>
            <Title level={4} className="!mb-0 !text-slate-950">
              Zebra Agent Desktop
            </Title>
            <Text className="text-slate-500">Local-first operator shell bootstrap</Text>
          </div>
        </Space>
        <Tag color="blue">{now}</Tag>
      </Header>
      <Content className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-6 py-6">
        <Card className="overflow-hidden border-0 shadow-[0_24px_80px_rgba(15,23,42,0.08)]">
          <Row gutter={[24, 24]} align="middle">
            <Col xs={24} lg={16}>
              <Space direction="vertical" size="middle" className="w-full">
                <Tag color="geekblue" className="w-fit">
                  Live API Integration
                </Tag>
                <Title className="!mb-0 !text-4xl !leading-tight !text-slate-950">
                  Zebra Agent 前端已经开始直接读取本地 operator surfaces
                </Title>
                <Paragraph className="!mb-0 !text-base !text-slate-600">
                  这一版不是纯静态壳子了。它已经接上 Zebra Agent 的 HTTP API，能看健康状态、审批队列、会话详情、
                  事件流，以及 repo 或 cross-scope memory 概览。
                </Paragraph>
              </Space>
            </Col>
            <Col xs={24} lg={8}>
              <Card className="border-slate-200 bg-slate-950 text-white">
                <Space direction="vertical" size="middle" className="w-full">
                  <Statistic
                    title={<span className="text-slate-300">API Health</span>}
                    value={healthQuery.data?.status === "ok" ? "online" : "unknown"}
                    valueStyle={{ color: "#ffffff", fontSize: 28 }}
                  />
                  <Text className="text-slate-300">{healthQuery.data?.service ?? "zebra-agent-api"}</Text>
                  {healthQuery.error ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="Health probe failed"
                      description={formatOperatorError(healthQuery.error)}
                    />
                  ) : null}
                </Space>
              </Card>
            </Col>
          </Row>
        </Card>

        <Row gutter={[24, 24]}>
          <Col xs={24} xl={10}>
            <OperatorConfigCard config={config} onChange={patchConfig} onReset={resetConfig} />
          </Col>
          <Col xs={24} xl={14}>
            <SessionComposerCard
              creating={busy}
              onCreate={actions.createSession}
            />
          </Col>
        </Row>

        <Row gutter={[24, 24]}>
          <Col xs={24} xl={9}>
            <ApprovalsCard
              approvals={approvalsQuery.data?.approvals}
              isLoading={approvalsQuery.isLoading}
              errorText={approvalsQuery.error ? formatOperatorError(approvalsQuery.error) : null}
              onSelect={(approvalId, sessionId) => void workbench.actions.selectApproval(approvalId, sessionId)}
            />
          </Col>
          <Col xs={24} xl={15}>
            <Space direction="vertical" size="large" className="w-full">
              <SessionControlCard
                session={sessionQuery.data}
                approvalDetail={approvalDetailQuery.data && "approval_id" in approvalDetailQuery.data ? approvalDetailQuery.data : undefined}
                busy={busy}
                errorText={
                  errorText ??
                  (approvalDetailQuery.error ? formatOperatorError(approvalDetailQuery.error) : null)
                }
                onApprove={actions.approve}
                onReject={actions.reject}
                onSuspend={actions.suspend}
                onCancel={actions.cancel}
                onResume={actions.resume}
              />
              <Row gutter={[24, 24]}>
                <Col xs={24} xl={10}>
                  <SessionMessageCard
                    disabled={busy || !config.sessionId.trim()}
                    onSubmit={actions.appendMessage}
                  />
                </Col>
                <Col xs={24} xl={14}>
                  <SessionDeliveryCard
                    disabled={busy || !config.sessionId.trim()}
                    onCommit={actions.commit}
                    onPullRequest={actions.pullRequest}
                  />
                </Col>
              </Row>
              <SessionInspectorCard
                session={sessionQuery.data}
                stream={streamQuery.data?.events}
                memory={memoryQuery.data}
                overview={overviewQuery.data}
                diff={diffQuery.data}
                artifacts={artifactsQuery.data}
                deliveryAudit={deliveryAuditQuery.data}
                isLoading={
                  sessionQuery.isLoading ||
                  streamQuery.isLoading ||
                  diffQuery.isLoading ||
                  memoryQuery.isLoading ||
                  artifactsQuery.isLoading ||
                  deliveryAuditQuery.isLoading ||
                  overviewQuery.isLoading
                }
                errorText={
                  sessionQuery.error
                    ? formatOperatorError(sessionQuery.error)
                    : streamQuery.error
                      ? formatOperatorError(streamQuery.error)
                      : diffQuery.error
                        ? formatOperatorError(diffQuery.error)
                        : memoryQuery.error
                          ? formatOperatorError(memoryQuery.error)
                          : artifactsQuery.error
                            ? formatOperatorError(artifactsQuery.error)
                            : deliveryAuditQuery.error
                              ? formatOperatorError(deliveryAuditQuery.error)
                              : overviewQuery.error
                                ? formatOperatorError(overviewQuery.error)
                                : null
                }
                selectedArtifact={selectedArtifact}
                artifactContentPreview={artifactContentPreview}
                onInspectArtifact={(artifactId) => void actions.inspectArtifact(artifactId)}
                onReadArtifact={(artifactId) => void actions.readArtifact(artifactId)}
                onPruneArtifact={(artifactId) => void actions.pruneArtifact(artifactId)}
                onCloseArtifactModal={actions.closeArtifactModal}
                onConfirmMemory={(memoryId) => void actions.confirmMemory(memoryId)}
                onExpireMemory={(memoryId) => void actions.expireMemory(memoryId)}
              />
              <MemoryQueueCard
                api={workbench.api}
                sessionId={config.sessionId}
                userId={config.userId}
                tenantId={config.tenantId}
                disabled={busy}
                onRefresh={actions.refreshSessionSurface}
              />
              <ScopeMemoryCard
                api={workbench.api}
                sessionId={config.sessionId}
                userId={config.userId}
                tenantId={config.tenantId}
              />
              <MemoryGovernanceCard
                api={workbench.api}
                sessionId={config.sessionId}
                authToken={config.authToken}
                apiBaseUrl={config.apiBaseUrl}
              />
            </Space>
          </Col>
        </Row>
      </Content>
    </Layout>
  );
}
