import { Button, Card, Form, Input, Space, Switch, Typography } from "antd";
import { useState } from "react";

interface SessionDeliveryCardProps {
  disabled: boolean;
  onCommit: (payload: {
    message: string;
    author_name?: string;
    author_email?: string;
  }) => Promise<unknown>;
  onPullRequest: (payload: {
    title: string;
    body: string;
    base_branch: string;
    head_branch?: string;
    dry_run: boolean;
  }) => Promise<unknown>;
}

export function SessionDeliveryCard({
  disabled,
  onCommit,
  onPullRequest,
}: SessionDeliveryCardProps) {
  const [commitMessage, setCommitMessage] = useState("Apply Zebra Agent session changes");
  const [prTitle, setPrTitle] = useState("Zebra Agent session changes");
  const [prBody, setPrBody] = useState("Generated from the Zebra Agent desktop UI.");
  const [baseBranch, setBaseBranch] = useState("main");
  const [headBranch, setHeadBranch] = useState("");
  const [dryRun, setDryRun] = useState(true);

  return (
    <Card title="Delivery Actions">
      <Space direction="vertical" size="large" className="w-full">
        <div>
          <Typography.Title level={5}>Commit</Typography.Title>
          <Space direction="vertical" size="middle" className="w-full">
            <Input
              value={commitMessage}
              disabled={disabled}
              onChange={(event) => setCommitMessage(event.target.value)}
              placeholder="Commit message"
            />
            <Button
              type="primary"
              disabled={disabled}
              onClick={() =>
                void onCommit({
                  message: commitMessage.trim(),
                })
              }
            >
              Create Commit
            </Button>
          </Space>
        </div>
        <div>
          <Typography.Title level={5}>Pull Request</Typography.Title>
          <Form layout="vertical">
            <Form.Item label="Title">
              <Input value={prTitle} disabled={disabled} onChange={(event) => setPrTitle(event.target.value)} />
            </Form.Item>
            <Form.Item label="Body">
              <Input.TextArea
                value={prBody}
                disabled={disabled}
                onChange={(event) => setPrBody(event.target.value)}
                autoSize={{ minRows: 3, maxRows: 8 }}
              />
            </Form.Item>
            <Form.Item label="Base Branch">
              <Input value={baseBranch} disabled={disabled} onChange={(event) => setBaseBranch(event.target.value)} />
            </Form.Item>
            <Form.Item label="Head Branch">
              <Input value={headBranch} disabled={disabled} onChange={(event) => setHeadBranch(event.target.value)} />
            </Form.Item>
            <Form.Item label="Dry Run">
              <Switch checked={dryRun} disabled={disabled} onChange={setDryRun} />
            </Form.Item>
          </Form>
          <Button
            disabled={disabled}
            onClick={() =>
              void onPullRequest({
                title: prTitle.trim(),
                body: prBody,
                base_branch: baseBranch.trim() || "main",
                head_branch: headBranch.trim() || undefined,
                dry_run: dryRun,
              })
            }
          >
            Open Pull Request
          </Button>
        </div>
      </Space>
    </Card>
  );
}
