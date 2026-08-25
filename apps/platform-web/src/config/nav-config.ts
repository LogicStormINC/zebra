import type { NavGroup } from '@/types';

/**
 * Zebra Agent Platform Console 导航配置
 *
 * 对应 PRD v1.1 第 7.2 节完整导航树与 7.3 节推荐路由。
 * 当前阶段不引入用户体系，导航不做 RBAC 过滤；
 * 接入 Operator Identity 后再按角色裁剪。
 */
export const navGroups: NavGroup[] = [
  {
    label: '概览',
    items: [
      {
        title: '平台总览',
        url: '/overview',
        icon: 'platform',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: '接入中心',
    items: [
      {
        title: '接入向导',
        url: '/integrations/onboarding',
        icon: 'forms',
        isActive: false,
        items: []
      },
      {
        title: 'Host 应用',
        url: '/integrations/hosts',
        icon: 'host',
        isActive: false,
        items: []
      },
      {
        title: '入站信任',
        url: '/integrations/trust',
        icon: 'trust',
        isActive: false,
        items: []
      },
      {
        title: 'Connector',
        url: '/integrations/connectors',
        icon: 'connector',
        isActive: false,
        items: []
      },
      {
        title: 'Backend Manifest',
        url: '/integrations/backend-manifests',
        icon: 'manifest',
        isActive: false,
        items: []
      },
      {
        title: 'Namespace Binding',
        url: '/integrations/bindings',
        icon: 'binding',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: 'Agent 资产',
    items: [
      {
        title: 'AgentDefinition',
        url: '/agents/definitions',
        icon: 'agent',
        isActive: false,
        items: []
      },
      {
        title: 'Agent Release',
        url: '/agents/releases',
        icon: 'agentRelease',
        isActive: false,
        items: []
      },
      {
        title: 'Capability Profile',
        url: '/agents/capability-profiles',
        icon: 'exclusive',
        isActive: false,
        items: []
      },
      {
        title: 'Model Policy',
        url: '/agents/policies/models',
        icon: 'evaluation',
        isActive: false,
        items: []
      },
      {
        title: 'Tool Policy',
        url: '/agents/policies/tools',
        icon: 'worker',
        isActive: false,
        items: []
      },
      {
        title: 'Memory Policy',
        url: '/agents/policies/memory',
        icon: 'post',
        isActive: false,
        items: []
      },
      {
        title: 'Runtime Policy',
        url: '/agents/policies/runtime',
        icon: 'settings',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: '运行中心',
    items: [
      {
        title: 'Task',
        url: '/runtime/tasks',
        icon: 'task',
        isActive: false,
        items: []
      },
      {
        title: 'Orchestration',
        url: '/runtime/orchestrations',
        icon: 'orchestration',
        isActive: false,
        items: []
      },
      {
        title: 'Subagent',
        url: '/runtime/subagents',
        icon: 'subagent',
        isActive: false,
        items: []
      },
      {
        title: 'Approval 与 Clarification',
        url: '/runtime/approvals',
        icon: 'approval',
        isActive: false,
        items: []
      },
      {
        title: 'Host Effect',
        url: '/runtime/host-effects',
        icon: 'effect',
        isActive: false,
        items: []
      },
      {
        title: 'Artifact',
        url: '/runtime/artifacts',
        icon: 'artifact',
        isActive: false,
        items: []
      },
      {
        title: 'Worker 状态',
        url: '/runtime/workers',
        icon: 'worker',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: '前端能力',
    items: [
      {
        title: 'Frontend Profile',
        url: '/frontend/profiles',
        icon: 'frontend',
        isActive: false,
        items: []
      },
      {
        title: 'Hook Contract',
        url: '/frontend/hooks',
        icon: 'hook',
        isActive: false,
        items: []
      },
      {
        title: 'Client Session',
        url: '/frontend/client-sessions',
        icon: 'clientSession',
        isActive: false,
        items: []
      },
      {
        title: 'Client Run Binding',
        url: '/frontend/client-bindings',
        icon: 'binding',
        isActive: false,
        items: []
      },
      {
        title: 'Client Effect',
        url: '/frontend/client-effects',
        icon: 'clientEffect',
        isActive: false,
        items: []
      },
      {
        title: 'Mounted Capability Inspector',
        url: '/frontend/mounted-inspector',
        icon: 'inspector',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: '质量与发布',
    items: [
      {
        title: 'Conformance Run',
        url: '/quality/conformance',
        icon: 'conformance',
        isActive: false,
        items: []
      },
      {
        title: 'Dry Run',
        url: '/quality/dry-runs',
        icon: 'dryRun',
        isActive: false,
        items: []
      },
      {
        title: 'Rollout',
        url: '/quality/rollouts',
        icon: 'rollout',
        isActive: false,
        items: []
      },
      {
        title: 'Evaluation',
        url: '/quality/evaluations',
        icon: 'evaluation',
        isActive: false,
        items: []
      },
      {
        title: 'Release Gate',
        url: '/quality/release-gates',
        icon: 'gate',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: '治理与审计',
    items: [
      {
        title: 'Policy',
        url: '/governance/policies',
        icon: 'policy',
        isActive: false,
        items: []
      },
      {
        title: 'Quota',
        url: '/governance/quotas',
        icon: 'quota',
        isActive: false,
        items: []
      },
      {
        title: 'Usage 与成本',
        url: '/governance/usage',
        icon: 'usage',
        isActive: false,
        items: []
      },
      {
        title: 'Audit Log',
        url: '/governance/audit',
        icon: 'audit',
        isActive: false,
        items: []
      },
      {
        title: 'Security Findings',
        url: '/governance/security',
        icon: 'security',
        isActive: false,
        items: []
      },
      {
        title: 'Effect Reconciliation',
        url: '/governance/reconciliation',
        icon: 'reconciliation',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: '系统设置',
    items: [
      {
        title: 'Environment',
        url: '/system/environments',
        icon: 'environment',
        isActive: false,
        items: []
      },
      {
        title: 'Operator 与角色',
        url: '/system/operators',
        icon: 'teams',
        isActive: false,
        items: []
      },
      {
        title: 'Feature Flag',
        url: '/system/feature-flags',
        icon: 'flag',
        isActive: false,
        items: []
      },
      {
        title: 'Credential Provider',
        url: '/system/credentials',
        icon: 'credential',
        isActive: false,
        items: []
      },
      {
        title: 'Notification',
        url: '/system/notifications',
        icon: 'notification',
        isActive: false,
        items: []
      },
      {
        title: 'Platform Health',
        url: '/system/health',
        icon: 'heartbeat',
        isActive: false,
        items: []
      }
    ]
  }
];
