import { cn } from '@/lib/utils';
import { Separator } from '@/components/ui/separator';
import type { ReactNode } from 'react';

/**
 * 页面头（PRD 8.1）：标题 + 描述 + 主操作按钮 + 版本与状态信息条。
 */
export function PageHeader({
  title,
  description,
  actions,
  meta,
  className
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** 版本与状态信息：Revision / Digest / Status / Created By / Created At / Effective Scope（PRD 6.2） */
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col gap-3 border-b p-4 md:px-6', className)}>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div className='min-w-0'>
          <h1 className='text-xl font-semibold tracking-tight md:text-2xl'>{title}</h1>
          {description && (
            <p className='text-muted-foreground mt-1 max-w-3xl text-sm'>{description}</p>
          )}
        </div>
        {actions && <div className='flex shrink-0 items-center gap-2'>{actions}</div>}
      </div>
      {meta && (
        <>
          <Separator />
          <div className='text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs'>
            {meta}
          </div>
        </>
      )}
    </div>
  );
}
