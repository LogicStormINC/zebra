'use client';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Icons } from '@/components/icons';
import { formatBytes, formatDateTime, formatNumber } from '@/lib/platform/format';
import { cn } from '@/lib/utils';
import type { Quota } from '@/lib/platform/types';
import { useState } from 'react';
import { toast } from 'sonner';

const DIMENSION_LABELS: Record<Quota['dimension'], string> = {
  concurrent_tasks: '并发 Task',
  model_tokens: '模型 Token',
  tool_calls: '工具调用',
  runtime_seconds: '运行时长（秒）',
  artifact_bytes: '产物存储（字节）',
  client_actions: '前端动作',
  subagents: '子 Agent',
  orchestration_nodes: '编排节点'
};

const RESET_CYCLE_LABELS: Record<Quota['resetCycle'], string> = {
  hourly: '每小时重置',
  daily: '每天重置',
  monthly: '每月重置'
};

function formatQuotaValue(dimension: Quota['dimension'], value: number): string {
  return dimension === 'artifact_bytes' ? formatBytes(value) : formatNumber(value);
}

function usageState(quota: Quota): 'over' | 'warning' | 'normal' {
  const pct = (quota.used / quota.softLimit) * 100;
  if (pct >= 100) return 'over';
  if (pct >= quota.warningThresholdPct) return 'warning';
  return 'normal';
}

export function QuotaTable({ quotas }: { quotas: Quota[] }) {
  const [adjusting, setAdjusting] = useState<Quota | null>(null);
  const [softInput, setSoftInput] = useState('');
  const [hardInput, setHardInput] = useState('');

  const openAdjust = (quota: Quota) => {
    setAdjusting(quota);
    setSoftInput(String(quota.softLimit));
    setHardInput(String(quota.hardLimit));
  };

  const submitAdjust = () => {
    if (!adjusting) return;
    const soft = Number(softInput);
    const hard = Number(hardInput);
    if (!Number.isFinite(soft) || !Number.isFinite(hard) || soft <= 0 || hard <= 0) {
      toast.error('请输入有效的正数限额');
      return;
    }
    if (soft > hard) {
      toast.error('Soft Limit 不能大于 Hard Limit');
      return;
    }
    toast.success('限额调整已提交（演示）', {
      description: `${adjusting.scope} · ${DIMENSION_LABELS[adjusting.dimension]}：soft ${formatQuotaValue(
        adjusting.dimension,
        soft
      )} / hard ${formatQuotaValue(adjusting.dimension, hard)}；变更将写入 Audit Log，上调需审批后生效`
    });
    setAdjusting(null);
  };

  return (
    <div className='flex flex-col gap-4'>
      <Alert>
        <Icons.quota />
        <AlertTitle>限额变更规则</AlertTitle>
        <AlertDescription>
          限额只能收窄或经审批上调：收窄立即生效；上调 Hard Limit 需 Platform Owner
          审批，并通过后写入 Audit Log。超过 Soft Limit 触发告警，达到 Hard Limit 时新请求被拒绝（fail
          closed）。
        </AlertDescription>
      </Alert>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted sticky top-0'>
            <TableRow>
              <TableHead>Scope</TableHead>
              <TableHead>Dimension</TableHead>
              <TableHead className='w-56'>使用率</TableHead>
              <TableHead className='text-right'>Soft Limit</TableHead>
              <TableHead className='text-right'>Hard Limit</TableHead>
              <TableHead className='text-right'>Warning</TableHead>
              <TableHead>Reset Cycle</TableHead>
              <TableHead>Updated At</TableHead>
              <TableHead className='text-right'>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {quotas.map((quota) => {
              const state = usageState(quota);
              const pct = Math.min((quota.used / quota.softLimit) * 100, 100);
              const overHard = quota.used >= quota.hardLimit;
              return (
                <TableRow key={quota.id}>
                  <TableCell className='font-mono text-xs whitespace-nowrap'>{quota.scope}</TableCell>
                  <TableCell>
                    <Badge variant='outline' className='text-xs'>
                      {DIMENSION_LABELS[quota.dimension]}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className='flex w-56 flex-col gap-1'>
                      <div className='h-1.5 w-full overflow-hidden rounded-full bg-muted'>
                        <div
                          className={cn(
                            'h-full rounded-full transition-all',
                            state === 'over'
                              ? 'bg-red-500'
                              : state === 'warning'
                                ? 'bg-amber-500'
                                : 'bg-emerald-500'
                          )}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <p
                        className={cn(
                          'text-xs tabular-nums',
                          state === 'over'
                            ? 'text-red-600 dark:text-red-400'
                            : state === 'warning'
                              ? 'text-amber-600 dark:text-amber-400'
                              : 'text-muted-foreground'
                        )}
                      >
                        {formatQuotaValue(quota.dimension, quota.used)} /{' '}
                        {formatQuotaValue(quota.dimension, quota.softLimit)}
                        {state === 'over' && ' · 超 Soft Limit'}
                        {overHard && ' · 已达 Hard Limit'}
                      </p>
                    </div>
                  </TableCell>
                  <TableCell className='text-right font-mono text-xs tabular-nums'>
                    {formatQuotaValue(quota.dimension, quota.softLimit)}
                  </TableCell>
                  <TableCell className='text-right font-mono text-xs tabular-nums'>
                    {formatQuotaValue(quota.dimension, quota.hardLimit)}
                  </TableCell>
                  <TableCell className='text-muted-foreground text-right text-xs tabular-nums'>
                    {quota.warningThresholdPct}%
                  </TableCell>
                  <TableCell className='text-xs whitespace-nowrap'>
                    {RESET_CYCLE_LABELS[quota.resetCycle]}
                  </TableCell>
                  <TableCell className='text-muted-foreground text-xs whitespace-nowrap'>
                    {formatDateTime(quota.updatedAt)}
                  </TableCell>
                  <TableCell className='text-right'>
                    <Button variant='outline' size='sm' onClick={() => openAdjust(quota)}>
                      调整限额
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <Dialog open={adjusting !== null} onOpenChange={(open) => !open && setAdjusting(null)}>
        <DialogContent>
          {adjusting && (
            <>
              <DialogHeader>
                <DialogTitle>调整限额</DialogTitle>
                <DialogDescription>
                  {adjusting.scope} · {DIMENSION_LABELS[adjusting.dimension]}（当前 r
                  {adjusting.softLimit}/{adjusting.hardLimit}）
                </DialogDescription>
              </DialogHeader>
              <div className='grid grid-cols-2 gap-3'>
                <div className='space-y-1.5'>
                  <Label htmlFor='quota-soft'>Soft Limit</Label>
                  <Input
                    id='quota-soft'
                    inputMode='numeric'
                    value={softInput}
                    onChange={(event) => setSoftInput(event.target.value)}
                  />
                </div>
                <div className='space-y-1.5'>
                  <Label htmlFor='quota-hard'>Hard Limit</Label>
                  <Input
                    id='quota-hard'
                    inputMode='numeric'
                    value={hardInput}
                    onChange={(event) => setHardInput(event.target.value)}
                  />
                </div>
              </div>
              <p className='text-muted-foreground text-xs'>
                当前用量 {formatQuotaValue(adjusting.dimension, adjusting.used)}。调整会写入 Audit
                Log；收窄立即生效，上调 Hard Limit 需 Platform Owner 审批。到达 Hard Limit
                后新请求将被拒绝。
              </p>
              <DialogFooter>
                <Button variant='outline' size='sm' onClick={() => setAdjusting(null)}>
                  取消
                </Button>
                <Button size='sm' onClick={submitAdjust}>
                  提交调整
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
