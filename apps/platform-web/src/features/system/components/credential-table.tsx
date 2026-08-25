'use client';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { StatusBadge } from '@/components/platform/status-badge';
import { Icons } from '@/components/icons';
import { relativeTime } from '@/lib/platform/format';
import { cn } from '@/lib/utils';
import type { CredentialProvider } from '@/lib/platform/types';

const STATUS_META: Record<CredentialProvider['status'], { label: string; tone: 'success' | 'warning' | 'failure' }> = {
  healthy: { label: '健康', tone: 'success' },
  degraded: { label: '降级', tone: 'warning' },
  unreachable: { label: '不可达', tone: 'failure' }
};

/**
 * 演示数据基准时间：与 mock 数据的 checkedAt 对齐。
 * 避免在渲染期调用 Date.now() 造成 SSR / hydration 抖动。
 */
const DEMO_REFERENCE = new Date('2026-08-26T10:00:00+08:00').getTime();

const DAY_MS = 24 * 60 * 60 * 1000;
const ROTATION_WINDOW_DAYS = 30;

function daysSinceRotated(iso: string): number {
  return Math.floor((DEMO_REFERENCE - new Date(iso).getTime()) / DAY_MS);
}

/**
 * Credential Provider 列表（PRD 6.5 合规边界）：
 * 仅管理 credential_ref 引用与元数据（rotation / health），
 * 任何明文 Secret 不进入页面、日志与浏览器存储。
 */
export function CredentialTable({ providers }: { providers: CredentialProvider[] }) {
  return (
    <div className='flex flex-col gap-4'>
      <Alert variant='destructive'>
        <Icons.lock />
        <AlertTitle>凭据合规边界（PRD 6.5）</AlertTitle>
        <AlertDescription>
          平台仅管理凭据引用与元数据（credential_ref / rotation / health），任何明文 Secret
          不进入页面、日志与浏览器存储。本页不提供查看或复制 Secret 值的任何入口。
        </AlertDescription>
      </Alert>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted sticky top-0'>
            <TableRow>
              <TableHead>Provider</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className='text-right'>Secret Count</TableHead>
              <TableHead>Last Rotated</TableHead>
              <TableHead>轮换提醒</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {providers.map((provider) => {
              const days = daysSinceRotated(provider.lastRotatedAt);
              const overdue = days >= ROTATION_WINDOW_DAYS;
              return (
                <TableRow key={provider.id}>
                  <TableCell className='font-medium'>
                    <span className='flex items-center gap-2'>
                      <Icons.credential className='text-muted-foreground size-3.5' />
                      {provider.provider}
                    </span>
                  </TableCell>
                  <TableCell>
                    <code className='bg-muted rounded px-1.5 py-0.5 font-mono text-xs'>{provider.kind}</code>
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={STATUS_META[provider.status].tone}>
                      {STATUS_META[provider.status].label}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className='text-right font-mono text-xs tabular-nums'>
                    {provider.secretCount} 个引用
                  </TableCell>
                  <TableCell className='text-muted-foreground text-xs whitespace-nowrap'>
                    {relativeTime(provider.lastRotatedAt)}
                  </TableCell>
                  <TableCell>
                    {overdue ? (
                      <StatusBadge tone='warning'>超 {ROTATION_WINDOW_DAYS} 天未轮换</StatusBadge>
                    ) : (
                      <span
                        className={cn(
                          'text-xs',
                          days >= ROTATION_WINDOW_DAYS - 9
                            ? 'text-amber-600 dark:text-amber-400'
                            : 'text-muted-foreground'
                        )}
                      >
                        {days} 天前已轮换
                        {days >= ROTATION_WINDOW_DAYS - 9 && '（接近 30 天窗口）'}
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <p className='text-muted-foreground flex items-center gap-1.5 text-xs'>
        <Icons.info className='size-3.5 shrink-0' />
        Secret 的下发与轮换只发生在服务端 Provider 侧；控制台仅展示引用计数与健康状态。
      </p>
    </div>
  );
}
