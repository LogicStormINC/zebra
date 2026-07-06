import { SendOutlined } from "@ant-design/icons";
import { Sender } from "@ant-design/x";
import { Button, Card, Input, Space, Switch, Typography } from "antd";
import { useState } from "react";
import type { CreateSessionResponse } from "../types";

interface SessionComposerCardProps {
  creating: boolean;
  onCreate: (payload: { title: string; prompt: string; execute: boolean }) => Promise<CreateSessionResponse>;
}

export function SessionComposerCard({ creating, onCreate }: SessionComposerCardProps) {
  const [title, setTitle] = useState("Desktop operator session");
  const [execute, setExecute] = useState(false);

  return (
    <Card title="Create Session" extra={<Switch checked={execute} onChange={setExecute} checkedChildren="Execute" unCheckedChildren="Plan" />}>
      <Space direction="vertical" size="middle" className="w-full">
        <Typography.Paragraph className="!mb-0 !text-slate-600">
          这里直接打 `POST /sessions`。创建成功后，UI 会自动把返回的 `session_id` 切成当前观察对象。
        </Typography.Paragraph>
        <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Session title" />
        <Sender
          submitType="enter"
          loading={creating}
          placeholder="Describe the coding task for Zebra Agent"
          prefix={<SendOutlined />}
          footer={() => (
            <Space>
              <Typography.Text type="secondary">Enter 提交，Shift+Enter 换行</Typography.Text>
            </Space>
          )}
          onSubmit={async (message) => {
            const normalized = message.trim();
            if (!normalized) {
              return;
            }
            await onCreate({
              title: title.trim() || "Desktop operator session",
              prompt: normalized,
              execute,
            });
          }}
        />
        <Button
          onClick={() => setTitle("Desktop operator session")}
          disabled={creating}
        >
          Reset title
        </Button>
      </Space>
    </Card>
  );
}
