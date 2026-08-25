'use client';

import { usePathname } from 'next/navigation';
import { useMemo } from 'react';

type BreadcrumbItem = {
  title: string;
  link: string;
};

/**
 * 路由段中文标签映射（对应 PRD 7.2 导航树）。
 * 未映射的段回退为首字母大写展示。
 */
const SEGMENT_LABELS: Record<string, string> = {
  overview: '平台总览',
  integrations: '接入中心',
  onboarding: '接入向导',
  hosts: 'Host 应用',
  trust: '入站信任',
  connectors: 'Connector',
  'backend-manifests': 'Backend Manifest',
  bindings: 'Namespace Binding',
  agents: 'Agent 资产',
  definitions: 'AgentDefinition',
  releases: 'Agent Release',
  'capability-profiles': 'Capability Profile',
  policies: 'Policy',
  models: 'Model Policy',
  tools: 'Tool Policy',
  memory: 'Memory Policy',
  runtime: 'Runtime Policy',
  tasks: 'Task',
  orchestrations: 'Orchestration',
  subagents: 'Subagent',
  approvals: 'Approval 与 Clarification',
  'host-effects': 'Host Effect',
  artifacts: 'Artifact',
  workers: 'Worker 状态',
  frontend: '前端能力',
  profiles: 'Frontend Profile',
  hooks: 'Hook Contract',
  'client-sessions': 'Client Session',
  'client-bindings': 'Client Run Binding',
  'client-effects': 'Client Effect',
  'mounted-inspector': 'Mounted Capability Inspector',
  quality: '质量与发布',
  conformance: 'Conformance Run',
  'dry-runs': 'Dry Run',
  rollouts: 'Rollout',
  evaluations: 'Evaluation',
  'release-gates': 'Release Gate',
  governance: '治理与审计',
  quotas: 'Quota',
  usage: 'Usage 与成本',
  audit: 'Audit Log',
  security: 'Security Findings',
  reconciliation: 'Effect Reconciliation',
  system: '系统设置',
  environments: 'Environment',
  operators: 'Operator 与角色',
  'feature-flags': 'Feature Flag',
  credentials: 'Credential Provider',
  notifications: 'Notification',
  health: 'Platform Health'
};

export function useBreadcrumbs() {
  const pathname = usePathname();

  const breadcrumbs = useMemo(() => {
    const segments = pathname.split('/').filter(Boolean);
    return segments.map((segment, index) => {
      const path = `/${segments.slice(0, index + 1).join('/')}`;
      const title =
        SEGMENT_LABELS[segment] ?? segment.charAt(0).toUpperCase() + segment.slice(1);
      return { title, link: path };
    });
  }, [pathname]);

  return breadcrumbs;
}
