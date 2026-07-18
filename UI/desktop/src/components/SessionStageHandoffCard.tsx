import { Alert, Button, Card, Form, Input, List, Modal, Space, Tag, Typography } from "antd";
import React from "react";
import { handoffBreadcrumb, isHandoffSafeBoundary } from "../lib/session-handoff";
import type {
  SessionHandoffPayload,
  SessionHandoffResponse,
  SessionSummary,
} from "../types";

interface SessionStageHandoffCardProps {
  busy: boolean;
  session: SessionSummary | null;
  onPreview: (payload: SessionHandoffPayload) => Promise<SessionHandoffResponse>;
  onCreate: (payload: SessionHandoffPayload) => Promise<SessionHandoffResponse>;
}

export function SessionStageHandoffCard({
  busy,
  session,
  onPreview,
  onCreate,
}: SessionStageHandoffCardProps) {
  const [form] = Form.useForm<SessionHandoffPayload>();
  const [preview, setPreview] = React.useState<SessionHandoffResponse | null>(null);
  const [created, setCreated] = React.useState<SessionHandoffResponse | null>(null);
  const safeBoundary = isHandoffSafeBoundary(session?.status);
  if (!session || !safeBoundary) return null;

  const values = (): SessionHandoffPayload => ({
    ...form.getFieldsValue(),
    reason: "user_phase_boundary",
  });
  const previewStage = async () => {
    await form.validateFields();
    setPreview(await onPreview(values()));
  };
  const confirmStage = async () => {
    await form.validateFields();
    Modal.confirm({
      title: "Start next stage?",
      content: "This creates one durable child Session. The current Session remains immutable.",
      okText: "Start next stage",
      onOk: async () => setCreated(await onCreate(values())),
    });
  };

  return (
    <Card size="small" title="阶段性新线程">
      <Space className="w-full" direction="vertical">
        <Alert
          showIcon
          type="info"
          message="当前会话位于安全阶段边界"
          description="先预览 handoff Envelope；确认后才会创建唯一子会话。"
        />
        <Form
          form={form}
          initialValues={{
            title: `Next: ${session.title}`,
            objective: session.title,
            stage_prompt: "Continue from the verified stage handoff.",
          }}
          layout="vertical"
        >
          <Form.Item label="下一阶段标题" name="title" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="目标" name="objective" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="首条阶段指令" name="stage_prompt" rules={[{ required: true }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
        <Space>
          <Button loading={busy} onClick={() => void previewStage()}>Preview Envelope</Button>
          <Button
            disabled={!preview}
            loading={busy}
            onClick={() => void confirmStage()}
            type="primary"
          >
            Start next stage
          </Button>
        </Space>
        {preview ? (
          <List
            bordered
            dataSource={preview.envelope.known_omissions}
            header={<Typography.Text strong>明确不携带</Typography.Text>}
            renderItem={(item) => <List.Item>{item}</List.Item>}
            size="small"
          />
        ) : null}
        {created ? (
          <Alert
            showIcon
            type="success"
            message={<><Tag>Stage {created.stage_index}</Tag>已导航到子会话</>}
            description={handoffBreadcrumb(created)}
          />
        ) : null}
      </Space>
    </Card>
  );
}
