import { Sender } from "@ant-design/x";
import { Card, Space, Typography } from "antd";
import { createStyles } from "antd-style";

const useStyle = createStyles(({ css }) => ({
  secondaryText: css`
    margin-bottom: 0;
    color: rgba(255, 255, 255, 0.58) !important;
  `,
}));

interface SessionMessageCardProps {
  disabled: boolean;
  onSubmit: (content: string) => Promise<unknown>;
}

export function SessionMessageCard({ disabled, onSubmit }: SessionMessageCardProps) {
  const { styles } = useStyle();
  return (
    <Card title="Append Message">
      <Space direction="vertical" size="middle" className="w-full">
        <Typography.Paragraph className={styles.secondaryText}>
          这里直接打 `POST /sessions/:session_id/messages`，用于给当前 session 补充新的 operator 指令。
        </Typography.Paragraph>
        <Sender
          disabled={disabled}
          submitType="enter"
          placeholder="Append an operator message to the current session"
          footer={() => (
            <Typography.Text type="secondary">
              适合继续推进、补约束、或者修正当前 session 的执行方向。
            </Typography.Text>
          )}
          onSubmit={async (message) => {
            const normalized = message.trim();
            if (!normalized) {
              return;
            }
            await onSubmit(normalized);
          }}
        />
      </Space>
    </Card>
  );
}
