/** 前端能力领域模型：Frontend Profile、Client Session、Client Effect、Mounted Snapshot。 */

export type ReadableContract = {
  name: string;
  description: string;
  sensitivity: 'public' | 'internal' | 'confidential' | 'restricted';
  maxBytes: number;
  updateStrategy: 'on_mount' | 'on_change' | 'manual' | 'debounced';
  contextPriority: number;
  /** 示例值 / 结构校验用的紧凑 JSON Schema 字符串。 */
  jsonSchema?: string;
  /** 注入上下文前按规则脱敏（如 mask/account、drop/email）。 */
  redactionRules?: string[];
  /** 绑定的宿主资源标识（如 trench.risk:read）。 */
  resourceBinding?: string;
};

export type ActionContract = {
  name: string;
  description: string;
  capability: string;
  risk: 'presentation' | 'navigation' | 'local_state' | 'user_interaction';
  executionMode: 'fire_and_receipt' | 'receipt_required' | 'human_confirmed';
  timeoutMs: number;
  requiresController: boolean;
  requiresUserConfirmation: boolean;
  /** 入参 JSON Schema 字符串（紧凑格式）。 */
  parametersSchema?: string;
  /** 回执结果 JSON Schema 字符串（紧凑格式）。 */
  resultSchema?: string;
  /** 回执结果大小上限（字节）。 */
  maxResultBytes?: number;
  /** 允许触发该 Action 的路由前缀白名单。 */
  allowedRoutes?: string[];
  /** 绑定的宿主资源标识列表。 */
  resourceBindings?: string[];
};

export type FrontendProfile = {
  id: string;
  hostAppId: string;
  frontendAppId: string;
  buildId: string;
  allowedOrigins: string[];
  readables: ReadableContract[];
  actions: ActionContract[];
  components: string[];
  revision: number;
  digest: string;
  status: 'draft' | 'published' | 'deprecated' | 'revoked';
  mountedClients: number;
  conformance: 'passed' | 'failed' | 'pending' | 'none';
  updatedAt: string;
};

export type ClientSession = {
  id: string;
  hostAppId: string;
  namespace: string;
  frontendAppId: string;
  buildId: string;
  origin: string;
  userSubjectHash: string;
  role: 'controller' | 'observer';
  taskId?: string;
  runId?: string;
  route: string;
  uiRevision: number;
  lastHeartbeatAt: string;
  status:
    | 'connecting'
    | 'active'
    | 'observer'
    | 'stale'
    | 'expired'
    | 'revoked'
    | 'disconnected';
};

export type ClientRunBinding = {
  id: string;
  taskId: string;
  runId: string;
  clientSessionId: string;
  frontendProfileDigest: string;
  snapshotDigest: string;
  status: 'active' | 'released' | 'expired';
  createdAt: string;
};

export type ClientEffect = {
  id: string;
  taskId: string;
  runId: string;
  action: string;
  hostAppId: string;
  frontendAppId: string;
  clientSessionId: string;
  status:
    | 'pending'
    | 'delivered'
    | 'succeeded'
    | 'failed'
    | 'declined'
    | 'unavailable'
    | 'stale_ui_state'
    | 'expired'
    | 'uncertain'
    | 'cancelled';
  expectedRevision: number;
  fenceHash: string;
  receiptDigest?: string;
  createdAt: string;
  expiresAt: string;
};

export type MountedCapabilitySnapshot = {
  clientSessionId: string;
  taskId?: string;
  runId?: string;
  route: string;
  frontendBuild: string;
  profileDigest: string;
  mountedSnapshotDigest: string;
  role: 'controller' | 'observer';
  uiRevision: number;
  heartbeatAt: string;
  mountedReadables: string[];
  mountedActions: string[];
  /** 当前实际挂载的注册式组件 ID（PRD 13.6）。 */
  mountedComponents: string[];
  driftStatus:
    | 'aligned'
    | 'profile_digest_mismatch'
    | 'unknown_action'
    | 'action_not_mounted'
    | 'schema_mismatch'
    | 'origin_mismatch'
    | 'build_mismatch'
    | 'stale_ui_revision'
    | 'stale_fence';
};
