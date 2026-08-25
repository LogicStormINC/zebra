import { StatusBadge } from '@/components/platform/status-badge';
import type { FrontendProfile } from '@/lib/platform/types';
import { SENSITIVITY_LABELS, SENSITIVITY_TONES } from './labels';

/** Readable 敏感度徽标（PRD 13.4）：四级配色 + 文字共同表达。 */
export function SensitivityBadge({
  sensitivity,
  className
}: {
  sensitivity: FrontendProfile['readables'][number]['sensitivity'];
  className?: string;
}) {
  return (
    <StatusBadge tone={SENSITIVITY_TONES[sensitivity]} className={className}>
      {SENSITIVITY_LABELS[sensitivity]}
    </StatusBadge>
  );
}
