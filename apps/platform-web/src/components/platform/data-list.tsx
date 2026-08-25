import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

/**
 * 详情页字段列表：label / value 网格（PRD 6.2 Digest 可见等要求）。
 */
export function DataList({
  items,
  columns = 2,
  className
}: {
  items: { label: string; value: ReactNode }[];
  columns?: 1 | 2 | 3;
  className?: string;
}) {
  const colClass = { 1: 'sm:grid-cols-1', 2: 'sm:grid-cols-2', 3: 'sm:grid-cols-3' }[columns];
  return (
    <dl className={cn('grid grid-cols-1 gap-x-6 gap-y-3', colClass, className)}>
      {items.map((item) => (
        <div key={item.label} className='min-w-0'>
          <dt className='text-muted-foreground text-xs'>{item.label}</dt>
          <dd className='mt-0.5 truncate text-sm font-medium'>{item.value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );
}
