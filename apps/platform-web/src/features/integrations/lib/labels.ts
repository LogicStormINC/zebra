import { lifecycleTone } from '@/lib/platform/status';
import type { StatusTone } from '@/lib/platform/types';

/** 接入中心展示标签与筛选项构建工具。 */

export const HOST_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  active: '已激活',
  suspended: '已暂停',
  revoked: '已撤销'
};

export const ENVIRONMENT_LABELS: Record<string, string> = {
  development: '开发',
  staging: '预发',
  production: '生产'
};

export const TRUST_HEALTH_LABELS: Record<string, string> = {
  healthy: '健康',
  warning: '告警',
  invalid: '失效'
};

export const CONFORMANCE_LABELS: Record<string, string> = {
  passed: '已通过',
  failed: '未通过',
  pending: '进行中',
  none: '未执行'
};

export const REVISION_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

export const BINDING_STATUS_LABELS: Record<string, string> = {
  active: '生效中',
  canary: '灰度中',
  'rolled-back': '已回滚',
  draft: '草稿'
};

export const CONNECTOR_HEALTH_LABELS: Record<string, string> = {
  healthy: '健康',
  degraded: '降级',
  unreachable: '不可达'
};

export const NAMESPACE_STRATEGY_LABELS: Record<string, string> = {
  fixed: '固定命名空间',
  'claim-mapped': '按 Claim 映射'
};

/** Host 生命周期徽标：suspended 归入 waiting，canary 归入 running，其余走 lifecycleTone。 */
export function hostStatusTone(status: string): StatusTone {
  if (status === 'suspended') return 'waiting';
  if (status === 'canary') return 'running';
  return lifecycleTone(status);
}

/** 从任意 label 表构建多选筛选项。 */
export function labelOptions(
  labels: Record<string, string>,
  order: string[] = Object.keys(labels)
) {
  return order.map((value) => ({ value, label: labels[value] ?? value }));
}
