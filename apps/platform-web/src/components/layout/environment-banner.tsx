'use client';
import { cn } from '@/lib/utils';
import { ENVIRONMENTS, useEnvironmentStore } from '@/lib/platform/environment-store';

/**
 * 非生产环境提示条（PRD 8.5）。
 * Production 环境不显示；其余环境顶部显示环境色条。
 */
export function EnvironmentBanner() {
  const environment = useEnvironmentStore((state) => state.environment);
  if (environment === 'production') return null;
  const label = ENVIRONMENTS.find((env) => env.id === environment)?.label ?? environment;
  return (
    <div
      className={cn(
        'flex h-6 shrink-0 items-center justify-center gap-2 px-4 text-xs font-medium',
        environment === 'staging'
          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
          : 'bg-sky-500/15 text-sky-700 dark:text-sky-400'
      )}
    >
      当前环境：{label} · 非生产环境仅允许 Dry Run 与 Canary，Production 发布门禁未解锁
    </div>
  );
}
