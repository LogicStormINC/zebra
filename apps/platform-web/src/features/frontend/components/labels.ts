import { lifecycleTone } from '@/lib/platform/status';
import type { StatusTone } from '@/lib/platform/types';
import type {
  ClientEffect,
  ClientSession,
  FrontendProfile,
  MountedCapabilitySnapshot
} from '@/lib/platform/types';

/**
 * 前端能力领域的中英文标签与语义色映射。
 * 颜色与文字共同表达状态（PRD 25.1）。
 */

export const SENSITIVITY_LABELS: Record<
  FrontendProfile['readables'][number]['sensitivity'],
  string
> = {
  public: '公开',
  internal: '内部',
  confidential: '机密',
  restricted: '受限'
};

export const SENSITIVITY_TONES: Record<
  FrontendProfile['readables'][number]['sensitivity'],
  StatusTone
> = {
  public: 'success',
  internal: 'running',
  confidential: 'warning',
  restricted: 'failure'
};

export const UPDATE_STRATEGY_LABELS: Record<
  FrontendProfile['readables'][number]['updateStrategy'],
  string
> = {
  on_mount: '挂载时',
  on_change: '变更时',
  manual: '手动',
  debounced: '防抖'
};

export const EXECUTION_MODE_LABELS: Record<
  FrontendProfile['actions'][number]['executionMode'],
  string
> = {
  fire_and_receipt: 'fire_and_receipt',
  receipt_required: 'receipt_required',
  human_confirmed: 'human_confirmed'
};

export const EXECUTION_MODE_TONES: Record<
  FrontendProfile['actions'][number]['executionMode'],
  StatusTone
> = {
  fire_and_receipt: 'success',
  receipt_required: 'running',
  human_confirmed: 'warning'
};

export const PROFILE_STATUS_LABELS: Record<FrontendProfile['status'], string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已弃用',
  revoked: '已撤销'
};

export const CONFORMANCE_LABELS: Record<FrontendProfile['conformance'], string> = {
  passed: '通过',
  failed: '失败',
  pending: '待运行',
  none: '未运行'
};

export const CONFORMANCE_TONES: Record<FrontendProfile['conformance'], StatusTone> = {
  passed: 'success',
  failed: 'failure',
  pending: 'waiting',
  none: 'draft'
};

export const ROLE_LABELS: Record<ClientSession['role'], string> = {
  controller: 'Controller',
  observer: 'Observer'
};

export const SESSION_STATUS_LABELS: Record<ClientSession['status'], string> = {
  connecting: '连接中',
  active: '活跃',
  observer: '观察态',
  stale: '心跳过期',
  expired: '已过期',
  revoked: '已撤销',
  disconnected: '已断开'
};

export const CLIENT_EFFECT_STATUS_LABELS: Record<ClientEffect['status'], string> = {
  pending: '待投递',
  delivered: '已投递',
  succeeded: '已执行',
  failed: '执行失败',
  declined: '客户端拒绝',
  unavailable: '客户端不可用',
  stale_ui_state: 'UI 状态过期',
  expired: '已过期',
  uncertain: '不确定',
  cancelled: '已取消'
};

export const DRIFT_LABELS: Record<MountedCapabilitySnapshot['driftStatus'], string> = {
  aligned: '一致（aligned）',
  profile_digest_mismatch: 'Profile 摘要不匹配',
  unknown_action: '未知 Action',
  action_not_mounted: 'Action 未挂载',
  schema_mismatch: 'Schema 不匹配',
  origin_mismatch: 'Origin 不匹配',
  build_mismatch: '构建不匹配',
  stale_ui_revision: 'UI Revision 过期',
  stale_fence: 'Fence 过期'
};

/** aligned 为绿；Fence/摘要类漂移为红，其余漂移类型为橙（PRD 13.8）。 */
export function driftTone(status: MountedCapabilitySnapshot['driftStatus']): StatusTone {
  if (status === 'aligned') return 'success';
  if (status === 'stale_fence' || status === 'profile_digest_mismatch') return 'failure';
  return 'uncertain';
}

/** Readables/Actions 禁止接入项（PRD 13.4）。 */
export const FORBIDDEN_READABLE_ITEMS = [
  'Cookie',
  'Token',
  'Secret',
  '完整 Redux Store',
  '完整 Zustand Store',
  '高频鼠标轨迹',
  '完整业务数据表'
];

export { lifecycleTone };
