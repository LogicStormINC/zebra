'use client';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useState } from 'react';

/**
 * 只读 JSON 展示块（PRD 25.4）：
 * 格式化、只读、复制；禁止渲染未净化 HTML。
 */
export function JsonBlock({
  value,
  className,
  maxHeight = 360,
  title
}: {
  value: unknown;
  className?: string;
  maxHeight?: number;
  title?: string;
}) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(value, null, 2);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // 静默降级
    }
  };

  return (
    <div className={cn('bg-muted/40 relative rounded-lg border', className)}>
      <div className='border-b px-3 py-1.5'>
        <div className='flex items-center justify-between'>
          <span className='text-muted-foreground font-mono text-xs'>
            {title ?? 'application/json'}
          </span>
          <Button variant='ghost' size='sm' className='h-6 px-2 text-xs' onClick={onCopy}>
            {copied ? (
              <Icons.check className='text-emerald-600 size-3' />
            ) : (
              <Icons.forms className='size-3' />
            )}
            {copied ? '已复制' : '复制'}
          </Button>
        </div>
      </div>
      <pre
        className='overflow-auto p-3 font-mono text-xs leading-relaxed'
        style={{ maxHeight }}
      >
        {text}
      </pre>
    </div>
  );
}
