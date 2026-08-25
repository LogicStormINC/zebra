import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { Icons } from '@/components/icons';
import Link from 'next/link';
import type { ReactNode } from 'react';

/**
 * KPI 卡片（PRD 9.2）：支持点击跳转到预置筛选列表。
 */
export function KpiCard({
  label,
  value,
  icon,
  hint,
  href,
  tone = 'default',
  className
}: {
  label: string;
  value: ReactNode;
  icon?: keyof typeof Icons;
  hint?: ReactNode;
  href?: string;
  tone?: 'default' | 'success' | 'warning' | 'failure';
  className?: string;
}) {
  const toneClass = {
    default: 'text-foreground',
    success: 'text-emerald-600 dark:text-emerald-400',
    warning: 'text-amber-600 dark:text-amber-400',
    failure: 'text-red-600 dark:text-red-400'
  }[tone];

  const Icon = icon ? Icons[icon] : null;

  const body = (
    <CardContent className='flex items-center justify-between gap-3 p-4'>
      <div className='min-w-0'>
        <p className='text-muted-foreground text-xs font-medium'>{label}</p>
        <p className={cn('mt-1 truncate text-2xl font-semibold tabular-nums', toneClass)}>
          {value}
        </p>
        {hint && <p className='text-muted-foreground mt-0.5 text-xs'>{hint}</p>}
      </div>
      {Icon && (
        <div className='bg-primary/10 text-primary flex size-10 shrink-0 items-center justify-center rounded-lg'>
          <Icon className='size-5' />
        </div>
      )}
    </CardContent>
  );

  return (
    <Card className={cn('py-0', href && 'transition-shadow hover:shadow-md', className)}>
      {href ? (
        <Link href={href} className='block'>
          {body}
        </Link>
      ) : (
        body
      )}
    </Card>
  );
}
