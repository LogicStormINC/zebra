import type { Environment } from './common';

/** 系统设置领域模型：Environment、Operator、Feature Flag、Credential Provider、Notification、Health。 */

export type EnvironmentRecord = {
  id: Environment;
  name: string;
  apiEndpoint: string;
  region: string;
  hosts: number;
  tasks24h: number;
  status: 'healthy' | 'degraded' | 'maintenance';
};

export type OperatorRecord = {
  id: string;
  name: string;
  email: string;
  roles: string[];
  status: 'active' | 'invited' | 'suspended';
  lastActiveAt: string;
};

export type FeatureFlag = {
  key: string;
  name: string;
  description: string;
  enabled: boolean;
  scope: 'platform' | 'environment' | 'host';
  updatedAt: string;
};

export type CredentialProvider = {
  id: string;
  provider: string;
  kind: string;
  status: 'healthy' | 'degraded' | 'unreachable';
  secretCount: number;
  lastRotatedAt: string;
};

export type NotificationRule = {
  id: string;
  event: string;
  channel: 'webhook' | 'email' | 'slack';
  target: string;
  enabled: boolean;
};

export type PlatformHealthCheck = {
  name: string;
  component: string;
  status: 'healthy' | 'degraded' | 'down';
  latencyMs: number;
  detail: string;
  checkedAt: string;
};
