import type {
  ClientEffect,
  ClientRunBinding,
  ClientSession,
  FrontendProfile,
  MountedCapabilitySnapshot
} from '@/lib/platform/types';

/** 前端能力 mock 数据：Frontend Profile、Client Session、Client Effect、Mounted Snapshot。 */

export const mockFrontendProfiles: FrontendProfile[] = [
  {
    id: 'fp_trench_web',
    hostAppId: 'trench',
    frontendAppId: 'trench-web',
    buildId: 'trw-20260824-3',
    allowedOrigins: ['https://app.trench.example'],
    readables: [
      {
        name: 'page.route',
        description: '当前路由路径',
        sensitivity: 'public',
        maxBytes: 256,
        updateStrategy: 'on_change',
        contextPriority: 10,
        jsonSchema: '{"type":"string","pattern":"^/"}',
        redactionRules: [],
        resourceBinding: 'client-state:route'
      },
      {
        name: 'risk.report_id',
        description: '当前打开的风险报告 ID',
        sensitivity: 'internal',
        maxBytes: 128,
        updateStrategy: 'on_change',
        contextPriority: 20,
        jsonSchema: '{"type":"string","pattern":"^RPT-[0-9]{4}-[0-9]{2}-[0-9]{2}$"}',
        redactionRules: ['mask/report_id'],
        resourceBinding: 'trench.risk:read'
      },
      {
        name: 'positions.selected_account',
        description: '用户选中的账户 ID（脱敏后注入）',
        sensitivity: 'confidential',
        maxBytes: 128,
        updateStrategy: 'manual',
        contextPriority: 30,
        jsonSchema: '{"type":"string","maxLength":24}',
        redactionRules: ['mask/account', 'drop/holder_name'],
        resourceBinding: 'trench.positions:read'
      }
    ],
    actions: [
      {
        name: 'ui.highlight_ticket',
        description: '在页面中高亮指定工单卡片',
        capability: 'presentation',
        risk: 'presentation',
        executionMode: 'receipt_required',
        timeoutMs: 8000,
        requiresController: true,
        requiresUserConfirmation: false,
        parametersSchema: '{"type":"object","properties":{"ticketId":{"type":"string","pattern":"^TR-[0-9]+$"}},"required":["ticketId"],"additionalProperties":false}',
        resultSchema: '{"type":"object","properties":{"highlighted":{"type":"boolean"}},"required":["highlighted"]}',
        maxResultBytes: 512,
        allowedRoutes: ['/risk', '/tickets'],
        resourceBindings: ['client-action:ui']
      },
      {
        name: 'ui.navigate_ticket',
        description: '导航到工单详情页',
        capability: 'navigation',
        risk: 'navigation',
        executionMode: 'fire_and_receipt',
        timeoutMs: 5000,
        requiresController: true,
        requiresUserConfirmation: false,
        parametersSchema: '{"type":"object","properties":{"ticketId":{"type":"string","pattern":"^TR-[0-9]+$"}},"required":["ticketId"],"additionalProperties":false}',
        resultSchema: '{"type":"object","properties":{"navigated":{"type":"boolean"}},"required":["navigated"]}',
        maxResultBytes: 256,
        allowedRoutes: ['/risk/reports', '/tickets'],
        resourceBindings: ['client-action:ui']
      },
      {
        name: 'ui.confirm_escalate',
        description: '弹出升级确认对话框（需用户点击）',
        capability: 'user_interaction',
        risk: 'user_interaction',
        executionMode: 'human_confirmed',
        timeoutMs: 120000,
        requiresController: true,
        requiresUserConfirmation: true,
        parametersSchema: '{"type":"object","properties":{"ticketId":{"type":"string"},"reason":{"type":"string","maxLength":200}},"required":["ticketId","reason"],"additionalProperties":false}',
        resultSchema: '{"type":"object","properties":{"confirmed":{"type":"boolean"},"reason":{"type":"string"}},"required":["confirmed"]}',
        maxResultBytes: 1024,
        allowedRoutes: ['/tickets'],
        resourceBindings: ['client-action:ui', 'trench.tickets:write']
      }
    ],
    components: ['TicketCard', 'RiskSummaryPanel'],
    revision: 4,
    digest: 'f1e2d3c4b5a6978869706152f3e4d5c6b7a89786',
    status: 'published',
    mountedClients: 3,
    conformance: 'passed',
    updatedAt: '2026-08-24T12:00:00+08:00'
  },
  {
    id: 'fp_jazz_web',
    hostAppId: 'jazz',
    frontendAppId: 'jazz-web',
    buildId: 'jzw-20260825-1',
    allowedOrigins: ['https://jazz.example'],
    readables: [
      {
        name: 'page.route',
        description: '当前路由路径',
        sensitivity: 'public',
        maxBytes: 256,
        updateStrategy: 'on_change',
        contextPriority: 10
      }
    ],
    actions: [],
    components: [],
    revision: 1,
    digest: 'a1b2c3d4e5f6071829304a5b6c7d8e9f00112233',
    status: 'draft',
    mountedClients: 0,
    conformance: 'pending',
    updatedAt: '2026-08-25T11:10:00+08:00'
  }
];

export const mockClientSessions: ClientSession[] = [
  {
    id: 'cs_9f21',
    hostAppId: 'trench',
    namespace: 'trench/canary',
    frontendAppId: 'trench-web',
    buildId: 'trw-20260824-3',
    origin: 'https://app.trench.example',
    userSubjectHash: 'u_sub_a91f…',
    role: 'controller',
    taskId: 'tsk_01JK2LH5WB',
    runId: 'run_c4471',
    route: '/risk/reports/2026-08-25',
    uiRevision: 12,
    lastHeartbeatAt: '2026-08-26T09:43:50+08:00',
    status: 'active'
  },
  {
    id: 'cs_8e30',
    hostAppId: 'trench',
    namespace: 'trench/prod',
    frontendAppId: 'trench-web',
    buildId: 'trw-20260824-3',
    origin: 'https://app.trench.example',
    userSubjectHash: 'u_sub_b82e…',
    role: 'observer',
    taskId: 'tsk_01JK2LH5WB',
    runId: 'run_c4471',
    route: '/risk/reports/2026-08-25',
    uiRevision: 12,
    lastHeartbeatAt: '2026-08-26T09:43:20+08:00',
    status: 'observer'
  },
  {
    id: 'cs_7d19',
    hostAppId: 'trench',
    namespace: 'trench/prod',
    frontendAppId: 'trench-web',
    buildId: 'trw-20260824-3',
    origin: 'https://console.trench.example',
    userSubjectHash: 'u_sub_c71d…',
    role: 'controller',
    taskId: 'tsk_01JK2M4Q8T',
    runId: 'run_d5582',
    route: '/pulls/482',
    uiRevision: 31,
    lastHeartbeatAt: '2026-08-26T09:42:10+08:00',
    status: 'active'
  },
  {
    id: 'cs_6c08',
    hostAppId: 'trench',
    namespace: 'trench/prod',
    frontendAppId: 'trench-web',
    buildId: 'trw-20260823-2',
    origin: 'https://app.trench.example',
    userSubjectHash: 'u_sub_d60c…',
    role: 'observer',
    route: '/tickets/TR-2291',
    uiRevision: 30,
    lastHeartbeatAt: '2026-08-25T19:12:00+08:00',
    status: 'stale'
  }
];

export const mockClientRunBindings: ClientRunBinding[] = [
  {
    id: 'crb_3301',
    taskId: 'tsk_01JK2LH5WB',
    runId: 'run_c4471',
    clientSessionId: 'cs_9f21',
    frontendProfileDigest: 'f1e2d3c4b5a69788…',
    snapshotDigest: '99a1b2c3d4e5f607…',
    status: 'active',
    createdAt: '2026-08-26T09:00:00+08:00'
  },
  {
    id: 'crb_3300',
    taskId: 'tsk_01JK2M4Q8T',
    runId: 'run_d5582',
    clientSessionId: 'cs_7d19',
    frontendProfileDigest: 'f1e2d3c4b5a69788…',
    snapshotDigest: '88b0a1c2d3e4f506…',
    status: 'active',
    createdAt: '2026-08-26T09:12:00+08:00'
  },
  {
    id: 'crb_3299',
    taskId: 'tsk_01JK2J7WNA',
    runId: 'run_b3360',
    clientSessionId: 'cs_6c08',
    frontendProfileDigest: 'f1e2d3c4b5a69788…',
    snapshotDigest: '77c0f9e8d7c6b505…',
    status: 'released',
    createdAt: '2026-08-25T10:02:00+08:00'
  }
];

export const mockClientEffects: ClientEffect[] = [
  {
    id: 'cefx_01HT5',
    taskId: 'tsk_01JK2LH5WB',
    runId: 'run_c4471',
    action: 'ui.highlight_ticket',
    hostAppId: 'trench',
    frontendAppId: 'trench-web',
    clientSessionId: 'cs_9f21',
    status: 'pending',
    expectedRevision: 12,
    fenceHash: 'fence_hash_9a21…',
    createdAt: '2026-08-26T09:14:30+08:00',
    expiresAt: '2026-08-26T09:22:30+08:00'
  },
  {
    id: 'cefx_01HT4',
    taskId: 'tsk_01JK2M4Q8T',
    runId: 'run_d5582',
    action: 'ui.highlight_ticket',
    hostAppId: 'trench',
    frontendAppId: 'trench-web',
    clientSessionId: 'cs_7d19',
    status: 'succeeded',
    expectedRevision: 31,
    fenceHash: 'fence_hash_8d30…',
    receiptDigest: 'rcpt_ce_4417',
    createdAt: '2026-08-26T09:31:40+08:00',
    expiresAt: '2026-08-26T09:39:40+08:00'
  },
  {
    id: 'cefx_01HT3',
    taskId: 'tsk_01JK2LH5WB',
    runId: 'run_c4471',
    action: 'ui.navigate_ticket',
    hostAppId: 'trench',
    frontendAppId: 'trench-web',
    clientSessionId: 'cs_8e30',
    status: 'declined',
    expectedRevision: 11,
    fenceHash: 'fence_hash_7c29…',
    createdAt: '2026-08-26T09:05:00+08:00',
    expiresAt: '2026-08-26T09:12:00+08:00'
  },
  {
    id: 'cefx_01HT2',
    taskId: 'tsk_01JK2J7WNA',
    runId: 'run_b3360',
    action: 'ui.navigate_ticket',
    hostAppId: 'trench',
    frontendAppId: 'trench-web',
    clientSessionId: 'cs_6c08',
    status: 'stale_ui_state',
    fenceHash: 'fence_hash_6b28…',
    expectedRevision: 30,
    createdAt: '2026-08-25T19:10:00+08:00',
    expiresAt: '2026-08-25T19:18:00+08:00'
  },
  {
    id: 'cefx_01HT1',
    taskId: 'tsk_01JK2J7WNA',
    runId: 'run_b3360',
    action: 'ui.highlight_ticket',
    hostAppId: 'trench',
    frontendAppId: 'trench-web',
    clientSessionId: 'cs_6c08',
    status: 'succeeded',
    expectedRevision: 30,
    fenceHash: 'fence_hash_5b27…',
    receiptDigest: 'rcpt_ce_4410',
    createdAt: '2026-08-25T10:08:00+08:00',
    expiresAt: '2026-08-25T10:16:00+08:00'
  }
];

export const mockMountedSnapshots: MountedCapabilitySnapshot[] = [
  {
    clientSessionId: 'cs_9f21',
    taskId: 'tsk_01JK2LH5WB',
    runId: 'run_c4471',
    route: '/risk/reports/2026-08-25',
    frontendBuild: 'trw-20260824-3',
    profileDigest: 'f1e2d3c4b5a69788…',
    mountedSnapshotDigest: 'snap_9f21_0826a',
    role: 'controller',
    uiRevision: 12,
    heartbeatAt: '2026-08-26T09:43:50+08:00',
    mountedReadables: ['page.route', 'risk.report_id'],
    mountedActions: ['ui.highlight_ticket', 'ui.navigate_ticket'],
    mountedComponents: ['TicketCard', 'RiskSummaryPanel'],
    driftStatus: 'aligned'
  },
  {
    clientSessionId: 'cs_8e30',
    taskId: 'tsk_01JK2LH5WB',
    runId: 'run_c4471',
    route: '/risk/reports/2026-08-25',
    frontendBuild: 'trw-20260824-3',
    profileDigest: 'f1e2d3c4b5a69788…',
    mountedSnapshotDigest: 'snap_8e30_0826a',
    role: 'observer',
    uiRevision: 11,
    heartbeatAt: '2026-08-26T09:43:20+08:00',
    mountedReadables: ['page.route'],
    mountedActions: ['ui.navigate_ticket'],
    mountedComponents: ['RiskSummaryPanel'],
    driftStatus: 'stale_ui_revision'
  },
  {
    clientSessionId: 'cs_6c08',
    route: '/tickets/TR-2291',
    frontendBuild: 'trw-20260823-2',
    profileDigest: 'e0d1c2b3a4958776…',
    mountedSnapshotDigest: 'snap_6c08_0825a',
    role: 'observer',
    uiRevision: 30,
    heartbeatAt: '2026-08-25T19:12:00+08:00',
    mountedReadables: ['page.route'],
    mountedActions: [],
    mountedComponents: ['TicketCard'],
    driftStatus: 'build_mismatch'
  }
];
