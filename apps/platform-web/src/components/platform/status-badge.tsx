'use client';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { StatusTone } from '@/lib/platform/types';

const TONE_CLASSES: Record<StatusTone, string> = {
  success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  running: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-400',
  waiting: 'border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-400',
  warning: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  failure: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-400',
  uncertain: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-400',
  draft: 'border-muted bg-muted/50 text-muted-foreground'
};

const TONE_DOT: Record<StatusTone, string> = {
  success: 'bg-emerald-500',
  running: 'bg-sky-500 animate-pulse',
  waiting: 'bg-violet-500',
  warning: 'bg-amber-500',
  failure: 'bg-red-500',
  uncertain: 'bg-orange-500',
  draft: 'bg-muted-foreground/60'
};

export function StatusBadge({
  tone,
  children,
  className,
  withDot = true
}: {
  tone: StatusTone;
  children: React.ReactNode;
  className?: string;
  withDot?: boolean;
}) {
  return (
    <Badge variant='outline' className={cn(TONE_CLASSES[tone], 'gap-1.5 font-medium', className)}>
      {withDot && <span className={cn('size-1.5 rounded-full', TONE_DOT[tone])} />}
      {children}
    </Badge>
  );
}
