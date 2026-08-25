'use client';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';

/**
 * 空状态（PRD 9.4 等）：图标 + 标题 + 描述 + 可选操作。
 */
export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
  icon = 'info'
}: {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: keyof typeof Icons;
}) {
  const Icon = Icons[icon] ?? Icons.info;
  return (
    <div className='flex flex-1 items-center justify-center p-8'>
      <div className='flex max-w-sm flex-col items-center gap-3 text-center'>
        <div className='bg-muted text-muted-foreground flex size-12 items-center justify-center rounded-full'>
          <Icon className='size-6' />
        </div>
        <div>
          <p className='font-medium'>{title}</p>
          {description && (
            <p className='text-muted-foreground mt-1 text-sm'>{description}</p>
          )}
        </div>
        {actionLabel && onAction && (
          <Button size='sm' onClick={onAction}>
            {actionLabel}
          </Button>
        )}
      </div>
    </div>
  );
}

/** API 失败等场景的可重试状态（PRD 30.2）。 */
export function ErrorState({
  title = '加载失败',
  description,
  onRetry
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <Alert variant='destructive' className='m-4'>
      <Icons.warning />
      <AlertTitle>{title}</AlertTitle>
      {description && <AlertDescription>{description}</AlertDescription>}
      {onRetry && (
        <Button size='sm' variant='outline' className='mt-2' onClick={onRetry}>
          重试
        </Button>
      )}
    </Alert>
  );
}
