import type { TaskPlan } from "./public-types.ts";

export function hasVisibleTaskPlan(plan: TaskPlan | undefined): plan is TaskPlan {
  return Boolean(plan?.steps.length);
}
