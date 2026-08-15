import { CheckOutlined, MinusOutlined } from "@ant-design/icons";
import { createStyles } from "antd-style";
import type { TaskPlan, TaskPlanStep } from "../core/public-types.ts";

const STATUS_LABELS: Record<TaskPlanStep["status"], string> = {
  pending: "待处理",
  in_progress: "进行中",
  completed: "已完成",
  cancelled: "已取消",
};

const useStyle = createStyles(({ css }) => ({
  card: css`
    border: 1px solid var(--task-ui-border, rgba(255, 255, 255, 0.08));
    border-radius: 16px;
    background: var(--task-ui-surface, rgba(255, 255, 255, 0.025));
    padding: 16px 18px;
  `,
  header: css`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 10px;
    h3 {
      margin: 0;
      color: var(--task-ui-text, #f4f4f5);
      font-size: 13px;
      line-height: 20px;
      font-weight: 600;
    }
    span {
      color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.42));
      font-size: 11px;
      line-height: 18px;
    }
  `,
  list: css`
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin: 0;
    padding: 0;
    list-style: none;
  `,
  step: css`
    min-width: 0;
    display: grid;
    grid-template-columns: 18px minmax(0, 1fr) auto;
    align-items: center;
    gap: 8px;
    min-height: 30px;
    color: var(--task-ui-text, rgba(255, 255, 255, 0.7));
    font-size: 13px;
    line-height: 20px;
    &[data-status="completed"],
    &[data-status="cancelled"] {
      color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.4));
    }
    &[data-status="in_progress"] {
      color: var(--task-ui-text, #f4f4f5);
    }
    small {
      color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.34));
      font-size: 11px;
      line-height: 18px;
      white-space: nowrap;
    }
  `,
  status: css`
    width: 16px;
    height: 16px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--task-ui-border, rgba(255, 255, 255, 0.15));
    border-radius: 50%;
    color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.58));
    font-size: 9px;
    [data-status="in_progress"] & {
      border-color: color-mix(in srgb, var(--task-ui-accent, rgb(245, 158, 11)) 58%, transparent);
      box-shadow: inset 0 0 0 4px color-mix(in srgb, var(--task-ui-accent, rgb(245, 158, 11)) 16%, transparent);
    }
  `,
}));

export function TaskPlan({ plan }: { plan: TaskPlan }) {
  const { styles } = useStyle();
  return (
    <section aria-label="任务计划" className={styles.card}>
      <div className={styles.header}>
        <h3>任务计划</h3>
        <span>{plan.summary.completed}/{plan.summary.total} 已完成</span>
      </div>
      <ol className={styles.list}>
        {plan.steps.map((step) => (
          <li className={styles.step} data-status={step.status} key={step.step_id}>
            <span aria-hidden="true" className={styles.status}>
              {step.status === "completed" ? <CheckOutlined /> : step.status === "cancelled" ? <MinusOutlined /> : null}
            </span>
            <span>{step.content}</span>
            <small>{STATUS_LABELS[step.status]}</small>
          </li>
        ))}
      </ol>
    </section>
  );
}
