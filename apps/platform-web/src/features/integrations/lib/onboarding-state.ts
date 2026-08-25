import type { Environment } from '@/lib/platform/types';

/** 接入向导（PRD 10.3）draft 状态模型与 localStorage 持久化。 */

export const DRAFT_STORAGE_KEY = 'zebra-onboarding-draft';

export type OnboardingBasic = {
  name: string;
  appId: string;
  ownerTeam: string;
  environment: Environment;
  description: string;
  contact: string;
  tags: string[];
};

export type OnboardingTrust = {
  issuer: string;
  audience: string;
  jwksUri: string;
  allowedOrigins: string[];
  algorithms: string[];
  policyVersion: string;
  namespaceStrategy: 'fixed' | 'claim-mapped';
};

export type OnboardingConnector = {
  connectorId: string;
  baseUri: string;
  manifestPath: string;
  invokePath: string;
  reconcilePath: string;
  protocolVersions: string[];
  workloadIdentityRef: string;
  credentialRef: string;
  networkPolicyRef: string;
  connectTimeoutSeconds: number;
  readTimeoutSeconds: number;
  maxRetries: number;
};

export type OnboardingFrontend = {
  frontendAppId: string;
  profileRevision: number;
  buildId: string;
  allowedOrigins: string[];
  readableCount: number;
  actionCount: number;
};

export type OnboardingAgents = {
  agentReleaseId: string;
  capabilityProfileId: string;
  policyId: string;
  quotaId: string;
};

export type OnboardingDraft = {
  step: number; // 1-7
  basic: OnboardingBasic;
  trust: OnboardingTrust;
  connector: OnboardingConnector;
  manifestJson: string;
  frontend: OnboardingFrontend;
  agents: OnboardingAgents;
};

export const ONBOARDING_STEPS = [
  '基础信息',
  '入站信任',
  '出站 Connector',
  'Backend Manifest',
  'Frontend Capability Profile',
  'Agent 与策略',
  '验证与发布'
] as const;

export const EMPTY_DRAFT: OnboardingDraft = {
  step: 1,
  basic: {
    name: '',
    appId: '',
    ownerTeam: '',
    environment: 'staging',
    description: '',
    contact: '',
    tags: []
  },
  trust: {
    issuer: '',
    audience: 'zebra-cloud-agent',
    jwksUri: '',
    allowedOrigins: [],
    algorithms: ['RS256'],
    policyVersion: 'trust-policy/v1',
    namespaceStrategy: 'fixed'
  },
  connector: {
    connectorId: '',
    baseUri: '',
    manifestPath: '/zebra/manifest',
    invokePath: '/zebra/tools/invoke',
    reconcilePath: '/zebra/effects/reconcile',
    protocolVersions: ['zebra-connector/1.2'],
    workloadIdentityRef: '',
    credentialRef: '',
    networkPolicyRef: '',
    connectTimeoutSeconds: 5,
    readTimeoutSeconds: 30,
    maxRetries: 3
  },
  manifestJson: '',
  frontend: {
    frontendAppId: '',
    profileRevision: 1,
    buildId: '',
    allowedOrigins: [],
    readableCount: 0,
    actionCount: 0
  },
  agents: {
    agentReleaseId: '',
    capabilityProfileId: '',
    policyId: '',
    quotaId: ''
  }
};

/** 各步骤必填校验（Step1：Name / App ID 非空，PRD 10.3）。 */
export function isStepComplete(draft: OnboardingDraft, step: number): boolean {
  switch (step) {
    case 1:
      return draft.basic.name.trim().length > 0 && draft.basic.appId.trim().length > 0;
    case 2:
      return (
        draft.trust.issuer.trim().length > 0 &&
        draft.trust.audience.trim().length > 0 &&
        draft.trust.jwksUri.trim().length > 0
      );
    case 3:
      return draft.connector.baseUri.trim().length > 0 && draft.connector.connectorId.trim().length > 0;
    case 4:
      return draft.manifestJson.trim().length > 0;
    case 5:
      return draft.frontend.frontendAppId.trim().length > 0;
    case 6:
      return draft.agents.agentReleaseId.trim().length > 0;
    default:
      return false;
  }
}

export function completedSteps(draft: OnboardingDraft): boolean[] {
  return ONBOARDING_STEPS.map((_, index) => isStepComplete(draft, index + 1));
}

export function loadDraft(): OnboardingDraft | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<OnboardingDraft>;
    return {
      ...EMPTY_DRAFT,
      ...parsed,
      basic: { ...EMPTY_DRAFT.basic, ...parsed.basic },
      trust: { ...EMPTY_DRAFT.trust, ...parsed.trust },
      connector: { ...EMPTY_DRAFT.connector, ...parsed.connector },
      frontend: { ...EMPTY_DRAFT.frontend, ...parsed.frontend },
      agents: { ...EMPTY_DRAFT.agents, ...parsed.agents }
    };
  } catch {
    return null;
  }
}

export function saveDraft(draft: OnboardingDraft): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
  } catch {
    // 存储不可用时静默降级（演示环境）
  }
}

export function clearDraft(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(DRAFT_STORAGE_KEY);
  } catch {
    // 静默降级
  }
}
