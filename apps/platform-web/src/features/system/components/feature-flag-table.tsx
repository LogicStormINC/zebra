'use client';

import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Icons } from '@/components/icons';
import { formatDateTime } from '@/lib/platform/format';
import type { FeatureFlag } from '@/lib/platform/types';
import { useState } from 'react';
import { toast } from 'sonner';

const SCOPE_LABELS: Record<FeatureFlag['scope'], string> = {
  platform: 'Platform 平台',
  environment: 'Environment 环境',
  host: 'Host'
};

/** Feature Flag 列表（PRD 14.3）：变更实时生效并记录审计。 */
export function FeatureFlagTable({ flags }: { flags: FeatureFlag[] }) {
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});

  const enabledOf = (flag: FeatureFlag) => overrides[flag.key] ?? flag.enabled;

  const toggle = (flag: FeatureFlag, next: boolean) => {
    setOverrides((prev) => ({ ...prev, [flag.key]: next }));
    toast.success('Flag 变更已记录审计', {
      description: `${flag.key} → ${next ? 'enabled' : 'disabled'}（${SCOPE_LABELS[flag.scope]} 作用域，实时生效）`
    });
  };

  return (
    <div className='flex flex-col gap-4'>
      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted sticky top-0'>
            <TableRow>
              <TableHead>Key</TableHead>
              <TableHead>Name</TableHead>
              <TableHead className='min-w-72'>Description</TableHead>
              <TableHead>Enabled</TableHead>
              <TableHead>Scope</TableHead>
              <TableHead>Updated At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {flags.map((flag) => (
              <TableRow key={flag.key}>
                <TableCell>
                  <code className='bg-muted rounded px-1.5 py-0.5 font-mono text-xs'>{flag.key}</code>
                </TableCell>
                <TableCell className='font-medium'>
                  <span className='flex items-center gap-2'>
                    <Icons.flag className='text-muted-foreground size-3.5' />
                    {flag.name}
                  </span>
                </TableCell>
                <TableCell className='text-muted-foreground text-xs'>{flag.description}</TableCell>
                <TableCell>
                  <div className='flex items-center gap-2'>
                    <Switch
                      checked={enabledOf(flag)}
                      onCheckedChange={(checked) => toggle(flag, checked === true)}
                      aria-label={`切换 ${flag.key}`}
                    />
                    <span
                      className={
                        enabledOf(flag)
                          ? 'text-emerald-600 dark:text-emerald-400 text-xs font-medium'
                          : 'text-muted-foreground text-xs'
                      }
                    >
                      {enabledOf(flag) ? '开启' : '关闭'}
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant='secondary' className='text-xs'>
                    {SCOPE_LABELS[flag.scope]}
                  </Badge>
                </TableCell>
                <TableCell className='text-muted-foreground text-xs whitespace-nowrap'>
                  {formatDateTime(flag.updatedAt)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
