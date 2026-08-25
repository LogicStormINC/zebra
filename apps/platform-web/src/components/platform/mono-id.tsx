'use client';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { useState } from 'react';

function middleTruncate(value: string, head = 10, tail = 6) {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/**
 * 等宽 ID / Digest 展示（PRD 25.2）：
 * 等宽字体、默认折叠、支持复制、悬停显示完整值。
 */
export function MonoId({
  value,
  className,
  head = 10,
  tail = 6,
  prefix,
  copyable = true
}: {
  value: string;
  className?: string;
  head?: number;
  tail?: number;
  prefix?: string;
  copyable?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard 不可用时静默降级
    }
  };

  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      <Tooltip>
        <TooltipTrigger
          render={
            <code className='bg-muted font-mono text-xs rounded px-1 py-0.5 whitespace-nowrap'>
              {prefix ? `${prefix} ` : ''}
              {middleTruncate(value, head, tail)}
            </code>
          }
        />
        <TooltipContent side='top' className='font-mono text-xs'>
          {value}
        </TooltipContent>
      </Tooltip>
      {copyable && (
        <Button
          variant='ghost'
          size='icon'
          className='size-5'
          aria-label='复制'
          onClick={onCopy}
        >
          {copied ? (
            <Icons.check className='text-emerald-600 size-3' />
          ) : (
            <Icons.forms className='text-muted-foreground size-3' />
          )}
        </Button>
      )}
    </span>
  );
}

/** Digest 徽标：默认显示前 12 位（PRD 6.2）。 */
export function DigestTag({ value, className }: { value: string; className?: string }) {
  return <MonoId value={value} head={12} tail={0} prefix='sha256:' className={className} />;
}
