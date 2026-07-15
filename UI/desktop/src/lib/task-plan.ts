import type { TaskPlan } from "../types";

export function hasVisibleTaskPlan(plan: TaskPlan | undefined): plan is TaskPlan {
  return Boolean(plan?.steps.length);
}
