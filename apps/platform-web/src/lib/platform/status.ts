import type { StatusTone, TaskStatus } from '@/lib/platform/types';

/**
 * 状态 → 语义色映射（PRD 25.1）。
 * 颜色与文字共同表达状态，禁止只依赖颜色。
 */
export function taskStatusTone(status: TaskStatus): StatusTone {
  switch (status) {
    case 'completed':
      return 'success';
    case 'running':
    case 'queued':
      return 'running';
    case 'waiting_approval':
    case 'waiting_clarification':
    case 'waiting_children':
    case 'waiting_client_effect':
    case 'suspended':
      return 'waiting';
    case 'blocked':
      return 'warning';
    case 'failed':
    case 'cancelled':
      return 'failure';
    case 'uncertain':
      return 'uncertain';
    default:
      return 'draft';
  }
}

export function lifecycleTone(status: string): StatusTone {
  switch (status) {
    case 'published':
    case 'active':
    case 'healthy':
    case 'passed':
    case 'succeeded':
    case 'matched':
    case 'aligned':
      return 'success';
    case 'running':
    case 'in-progress':
    case 'delivered':
    case 'connecting':
    case 'draining':
    case 'degraded':
      return 'running';
    case 'pending':
    case 'waiting':
    case 'stale':
    case 'planning':
    case 'invited':
      return 'waiting';
    case 'warning':
    case 'manual_review':
    case 'mismatched':
    case 'missing_receipt':
    case 'acknowledged':
      return 'warning';
    case 'failed':
    case 'revoked':
    case 'rejected':
    case 'unreachable':
    case 'down':
    case 'expired':
    case 'invalid':
    case 'denied':
    case 'cancelled':
    case 'declined':
    case 'unavailable':
      return 'failure';
    case 'uncertain':
    case 'stale_ui_state':
      return 'uncertain';
    default:
      return 'draft';
  }
}

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  queued: '排队中',
  running: '运行中',
  waiting_approval: '等待审批',
  waiting_clarification: '等待澄清',
  waiting_children: '等待子任务',
  waiting_client_effect: '等待前端执行',
  suspended: '已挂起',
  blocked: '阻塞',
  uncertain: '不确定',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消'
};

/** 生命周期状态通用文案（draft/published/deprecated/revoked），与各 feature 的 LIFECYCLE_LABELS 保持一致。 */
export const LIFECYCLE_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

/** Client Run Binding 状态文案，与 frontend/client-bindings-table 的用词保持一致。 */
export const CLIENT_BINDING_STATUS_LABELS: Record<string, string> = {
  active: '生效中',
  released: '已释放',
  expired: '已过期'
};
