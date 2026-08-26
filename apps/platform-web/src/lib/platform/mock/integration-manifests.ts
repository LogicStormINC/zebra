import type { BackendManifest } from '@/lib/platform/types';
/** 接入中心 Manifest mock 数据（自 integration.ts 拆出，守住 500 行硬限）。 */

export const mockManifests: BackendManifest[] = [
  {
    id: 'bm_trench_v5',
    hostAppId: 'trench',
    protocolVersion: 'zebra-manifest/1.2',
    revision: 5,
    readTools: 4,
    writeTools: 2,
    reconcileTools: 2,
    digest: 'be55cc3a118d40ee9922118d40ee9922118d40ee',
    status: 'published',
    conformance: 'passed',
    createdBy: 'lukeding',
    createdAt: '2026-08-20T14:00:00+08:00',
    tools: [
      {
        name: 'trench.get_position',
        description: '读取指定账户的当前持仓与风险敞口',
        capability: 'position:read',
        grantScopes: ['trench.positions:read'],
        risk: 'read',
        idempotency: 'none',
        timeoutSeconds: 10,
        maxOutputBytes: 65536,
        reconcileCapable: false,
        argumentSchema: {
          type: 'object',
          properties: { account_id: { type: 'string' } },
          required: ['account_id']
        }
      },
      {
        name: 'trench.get_risk_report',
        description: '读取当日风险报告摘要',
        capability: 'risk:read',
        grantScopes: ['trench.risk:read'],
        risk: 'read',
        idempotency: 'none',
        timeoutSeconds: 15,
        maxOutputBytes: 131072,
        reconcileCapable: false,
        argumentSchema: { type: 'object', properties: { date: { type: 'string' } } }
      },
      {
        name: 'trench.create_ticket',
        description: '在 Trench 内创建风控工单',
        capability: 'ticket:write',
        grantScopes: ['trench.tickets:write'],
        risk: 'medium',
        idempotency: 'idempotency_key',
        timeoutSeconds: 20,
        maxOutputBytes: 16384,
        reconcileCapable: true,
        argumentSchema: {
          type: 'object',
          properties: {
            title: { type: 'string' },
            severity: { enum: ['low', 'medium', 'high'] }
          },
          required: ['title']
        }
      },
      {
        name: 'trench.update_ticket_status',
        description: '更新工单状态（写操作，支持对账）',
        capability: 'ticket:write',
        grantScopes: ['trench.tickets:write'],
        risk: 'high',
        idempotency: 'idempotency_key',
        timeoutSeconds: 20,
        maxOutputBytes: 16384,
        reconcileCapable: true,
        argumentSchema: {
          type: 'object',
          properties: {
            ticket_id: { type: 'string' },
            status: { enum: ['open', 'resolved', 'escalated'] }
          },
          required: ['ticket_id', 'status']
        }
      }
    ]
  },
  {
    id: 'bm_jazz_v1',
    hostAppId: 'jazz',
    protocolVersion: 'zebra-manifest/1.2',
    revision: 1,
    readTools: 2,
    writeTools: 0,
    reconcileTools: 0,
    digest: '0f11aa8c99e2470bbb3399e2470bbb3399e2470b',
    status: 'draft',
    conformance: 'pending',
    createdBy: 'jazz-integrator',
    createdAt: '2026-08-25T11:00:00+08:00',
    tools: [
      {
        name: 'jazz.list_drafts',
        description: '列出待审核内容草稿',
        capability: 'content:read',
        grantScopes: ['jazz.content:read'],
        risk: 'read',
        idempotency: 'none',
        timeoutSeconds: 10,
        maxOutputBytes: 65536,
        reconcileCapable: false,
        argumentSchema: { type: 'object', properties: { page: { type: 'number' } } }
      },
      {
        name: 'jazz.get_content_policy',
        description: '读取内容政策文本',
        capability: 'policy:read',
        grantScopes: ['jazz.policy:read'],
        risk: 'read',
        idempotency: 'none',
        timeoutSeconds: 10,
        maxOutputBytes: 32768,
        reconcileCapable: false,
        argumentSchema: { type: 'object' }
      }
    ]
  },
  {
    id: 'bm_fake_a_v2',
    hostAppId: 'fake-host-a',
    protocolVersion: 'zebra-manifest/1.1',
    revision: 2,
    readTools: 1,
    writeTools: 1,
    reconcileTools: 1,
    digest: '77dd33aa22bb4c88f10022bb4c88f10022bb4c88',
    status: 'published',
    conformance: 'passed',
    createdBy: 'qa',
    createdAt: '2026-08-24T08:20:00+08:00',
    tools: [
      {
        name: 'fake_a.echo',
        description: '回显输入（Conformance 用）',
        capability: 'test:read',
        grantScopes: ['fake-a.test:read'],
        risk: 'read',
        idempotency: 'none',
        timeoutSeconds: 5,
        maxOutputBytes: 4096,
        reconcileCapable: false,
        argumentSchema: { type: 'object', properties: { message: { type: 'string' } } }
      },
      {
        name: 'fake_a.write_marker',
        description: '写入测试标记（写操作验收）',
        capability: 'test:write',
        grantScopes: ['fake-a.test:write'],
        risk: 'medium',
        idempotency: 'idempotency_key',
        timeoutSeconds: 5,
        maxOutputBytes: 4096,
        reconcileCapable: true,
        argumentSchema: { type: 'object', properties: { marker: { type: 'string' } } }
      }
    ]
  },
  {
    id: 'bm_fake_b_v1',
    hostAppId: 'fake-host-b',
    protocolVersion: 'zebra-manifest/1.1',
    revision: 1,
    readTools: 1,
    writeTools: 1,
    reconcileTools: 1,
    digest: '11ffbb7733cc4d99ee2233cc4d99ee2233cc4d99',
    status: 'published',
    conformance: 'failed',
    createdBy: 'qa',
    createdAt: '2026-08-22T15:00:00+08:00',
    tools: [
      {
        name: 'fake_b.echo',
        description: '回显输入（Conformance 用）',
        capability: 'test:read',
        grantScopes: ['fake-b.test:read'],
        risk: 'read',
        idempotency: 'none',
        timeoutSeconds: 5,
        maxOutputBytes: 4096,
        reconcileCapable: false,
        argumentSchema: { type: 'object', properties: { message: { type: 'string' } } }
      },
      {
        name: 'fake_b.write_marker',
        description: '写入测试标记（对账失败场景验收）',
        capability: 'test:write',
        grantScopes: ['fake-b.test:write'],
        risk: 'high',
        idempotency: 'idempotency_key',
        timeoutSeconds: 5,
        maxOutputBytes: 4096,
        reconcileCapable: true,
        argumentSchema: { type: 'object', properties: { marker: { type: 'string' } } }
      }
    ]
  }
];
