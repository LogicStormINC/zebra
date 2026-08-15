import { QuestionCircleOutlined } from "@ant-design/icons";
import { Button, Input } from "antd";
import { createStyles } from "antd-style";
import { useState } from "react";
import type { ClarificationContext } from "../core/public-types.ts";

const useStyle = createStyles(({ css }) => ({
  panel: css`
    padding: 18px;
    border: 1px solid color-mix(in srgb, var(--task-ui-accent, rgb(245, 158, 11)) 28%, transparent);
    border-radius: 16px;
    background: color-mix(in srgb, var(--task-ui-accent, rgb(245, 158, 11)) 5.5%, transparent);
  `,
  heading: css`
    display: flex;
    align-items: center;
    gap: 9px;
    margin: 0 0 8px;
    color: var(--task-ui-text, #f4f4f5);
    font-size: 14px;
    line-height: 22px;
    font-weight: 600;
    svg { color: var(--task-ui-accent, #f5a623); }
  `,
  question: css`
    margin: 0;
    color: var(--task-ui-text, rgba(255, 255, 255, 0.82));
    font-size: 14px;
    line-height: 22px;
  `,
  context: css`
    margin: 6px 0 0;
    color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.46));
    font-size: 12px;
    line-height: 19px;
  `,
  choices: css`
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 14px;
  `,
  response: css`
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px;
    margin-top: 12px;
    @media (max-width: 640px) { grid-template-columns: 1fr; }
  `,
}));

interface ClarificationCardProps {
  clarification: ClarificationContext | undefined;
  busy: boolean;
  onRespond: (clarificationId: string, content: string) => Promise<unknown>;
}

export function ClarificationCard({
  clarification,
  busy,
  onRespond,
}: ClarificationCardProps) {
  const { styles } = useStyle();
  const [response, setResponse] = useState("");
  if (!clarification) return null;

  const submit = (content: string) => {
    const normalized = content.trim();
    if (!normalized || busy) return;
    void onRespond(clarification.clarification_id, normalized)
      .then(() => setResponse(""))
      .catch(() => undefined);
  };

  return (
    <section aria-live="polite" className={styles.panel}>
      <h3 className={styles.heading}>
        <QuestionCircleOutlined /> Agent 需要补充信息
      </h3>
      <p className={styles.question}>{clarification.question}</p>
      {clarification.context ? <p className={styles.context}>{clarification.context}</p> : null}
      {clarification.choices.length ? (
        <div className={styles.choices}>
          {clarification.choices.map((choice) => (
            <Button disabled={busy} key={choice} onClick={() => submit(choice)}>
              {choice}
            </Button>
          ))}
        </div>
      ) : null}
      <div className={styles.response}>
        <Input
          aria-label="澄清回答"
          disabled={busy}
          onChange={(event) => setResponse(event.target.value)}
          onPressEnter={() => submit(response)}
          placeholder="输入补充信息"
          value={response}
        />
        <Button disabled={!response.trim()} loading={busy} onClick={() => submit(response)} type="primary">
          提交回答
        </Button>
      </div>
    </section>
  );
}
