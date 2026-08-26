'use client';

/**
 * 全局环境上下文（PRD 8.2 / 8.5）。
 *
 * 当前阶段无用户体系，环境选择仅作为前端展示上下文，
 * 接入 Management API 后由服务端确认环境作用域。
 * 非生产环境在 Shell 顶部显示环境色条。
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type EnvironmentId = 'development' | 'staging' | 'production';

export const ENVIRONMENTS: { id: EnvironmentId; label: string; namespace: string }[] = [
  { id: 'development', label: 'Development', namespace: 'zebra-dev' },
  { id: 'staging', label: 'Staging', namespace: 'zebra-staging' },
  { id: 'production', label: 'Production', namespace: 'zebra-prod' }
];

interface EnvironmentState {
  environment: EnvironmentId;
  setEnvironment: (env: EnvironmentId) => void;
}

export const useEnvironmentStore = create<EnvironmentState>()(
  persist(
    (set) => ({
      environment: 'development',
      setEnvironment: (environment) => set({ environment })
    }),
    { name: 'zebra-environment' }
  )
);

export function environmentLabel(id: EnvironmentId) {
  return ENVIRONMENTS.find((env) => env.id === id)?.label ?? id;
}

export function environmentNamespace(id: EnvironmentId) {
  return ENVIRONMENTS.find((env) => env.id === id)?.namespace ?? id;
}
