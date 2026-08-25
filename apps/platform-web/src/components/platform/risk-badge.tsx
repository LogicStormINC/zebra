import { StatusBadge } from './status-badge';

/** 风险等级徽标（PRD 12.2 / 18.9）。 */
const RISK_META: Record<string, { label: string; tone: 'success' | 'running' | 'waiting' | 'failure' }> = {
  read: { label: 'Read', tone: 'success' },
  low: { label: '低风险', tone: 'running' },
  medium: { label: '中风险', tone: 'waiting' },
  high: { label: '高风险', tone: 'failure' },
  presentation: { label: '展示', tone: 'success' },
  navigation: { label: '导航', tone: 'running' },
  local_state: { label: '本地状态', tone: 'waiting' },
  user_interaction: { label: '用户交互', tone: 'failure' }
};

export function RiskBadge({ risk, className }: { risk: string; className?: string }) {
  const meta = RISK_META[risk] ?? { label: risk, tone: 'draft' as const };
  return (
    <StatusBadge tone={meta.tone} className={className}>
      {meta.label}
    </StatusBadge>
  );
}
