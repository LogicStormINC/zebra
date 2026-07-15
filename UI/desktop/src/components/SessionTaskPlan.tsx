import { CheckOutlined, MinusOutlined } from "@ant-design/icons";
import type { TaskPlan, TaskPlanStep } from "../types";
import { useSessionTaskPlanStyle } from "./SessionTaskPlan.styles";

const STATUS_LABELS: Record<TaskPlanStep["status"], string> = {
  pending: "待处理",
  in_progress: "进行中",
  completed: "已完成",
  cancelled: "已取消",
};

export function SessionTaskPlan({ plan }: { plan: TaskPlan }) {
  const { styles } = useSessionTaskPlanStyle();
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
