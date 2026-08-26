'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { KpiCard } from '@/components/platform/kpi-card';
import { Icons } from '@/components/icons';
import { formatNumber, formatUsd } from '@/lib/platform/format';
import type { UsageRecord } from '@/lib/platform/types';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { downloadCsv } from '../export-csv';
import { UsageCharts, aggregateDaily } from './usage-charts';

const HOST_OPTIONS = ['trench', 'fake-host-a', 'jazz'] as const;

type HostFilter = 'all' | (typeof HOST_OPTIONS)[number];

type HostUsageSummary = {
  hostAppId: string;
  tokens: number;
  costUsd: number;
  taskCount: number;
  successRate: number;
  runtimeSeconds: number;
};

function formatHours(seconds: number): string {
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
  if (seconds >= 60) return `${(seconds / 60).toFixed(0)}m`;
  return `${seconds}s`;
}

function summarize(records: UsageRecord[]) {
  return records.reduce(
    (acc, record) => {
      acc.inputTokens += record.inputTokens;
      acc.outputTokens += record.outputTokens;
      acc.reasoningTokens += record.reasoningTokens;
      acc.modelCostUsd = Number((acc.modelCostUsd + record.modelCostUsd).toFixed(2));
      acc.runtimeSeconds += record.runtimeSeconds;
      acc.toolCalls += record.toolCalls;
      acc.clientActions += record.clientActions;
      acc.taskCount += record.taskCount;
      acc.weightedSuccess += record.successRate * record.taskCount;
      return acc;
    },
    {
      inputTokens: 0,
      outputTokens: 0,
      reasoningTokens: 0,
      modelCostUsd: 0,
      runtimeSeconds: 0,
      toolCalls: 0,
      clientActions: 0,
      taskCount: 0,
      weightedSuccess: 0
    }
  );
}

/** Usage 与成本视图（PRD 22）：Host 维度筛选 + KPI + 图表 + Host 汇总 + CSV 导出。 */
export function UsageView({ usage }: { usage: UsageRecord[] }) {
  const [host, setHost] = useState<HostFilter>('all');

  const filtered = useMemo(
    () => (host === 'all' ? usage : usage.filter((record) => record.hostAppId === host)),
    [usage, host]
  );

  const totals = useMemo(() => summarize(filtered), [filtered]);
  const daily = useMemo(() => aggregateDaily(filtered), [filtered]);
  const successRate = totals.taskCount > 0 ? totals.weightedSuccess / totals.taskCount : 0;

  const hostSummaries = useMemo<HostUsageSummary[]>(() => {
    const byHost = new Map<string, UsageRecord[]>();
    for (const record of filtered) {
      byHost.set(record.hostAppId, [...(byHost.get(record.hostAppId) ?? []), record]);
    }
    return [...byHost.entries()]
      .map(([hostAppId, records]) => {
        const agg = summarize(records);
        return {
          hostAppId,
          tokens: agg.inputTokens + agg.outputTokens + agg.reasoningTokens,
          costUsd: agg.modelCostUsd,
          taskCount: agg.taskCount,
          successRate: agg.taskCount > 0 ? agg.weightedSuccess / agg.taskCount : 0,
          runtimeSeconds: agg.runtimeSeconds
        };
      })
      .toSorted((a, b) => b.costUsd - a.costUsd);
  }, [filtered]);

  const dateRange = useMemo(() => {
    if (daily.length === 0) return { start: '—', end: '—', days: 0 };
    return { start: daily[0].date, end: daily[daily.length - 1].date, days: daily.length };
  }, [daily]);

  const onExport = () => {
    const rows: (string | number)[][] = [
      [
        'date',
        'host',
        'input_tokens',
        'output_tokens',
        'reasoning_tokens',
        'model_cost_usd',
        'runtime_seconds',
        'tool_calls',
        'client_actions',
        'task_count',
        'success_rate'
      ],
      ...filtered
        .toSorted((a, b) => a.date.localeCompare(b.date) || a.hostAppId.localeCompare(b.hostAppId))
        .map((record) => [
          record.date,
          record.hostAppId,
          record.inputTokens,
          record.outputTokens,
          record.reasoningTokens,
          record.modelCostUsd,
          record.runtimeSeconds,
          record.toolCalls,
          record.clientActions,
          record.taskCount,
          record.successRate
        ])
    ];
    const hostLabel = host === 'all' ? 'all-hosts' : host;
    downloadCsv(`usage-${hostLabel}-${dateRange.end}.csv`, rows, true);
    toast.success('导出已生成，操作已记录审计', {
      description: `usage-${hostLabel}-${dateRange.end}.csv · ${filtered.length} 行 · 含校验摘要（PRD 22.3）`
    });
  };

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <Select value={host} onValueChange={(value) => setHost((value ?? 'all') as HostFilter)}>
          <SelectTrigger size='sm' className='w-40'>
            <SelectValue placeholder='Host' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部 Host</SelectItem>
              {HOST_OPTIONS.map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Badge variant='outline' className='text-muted-foreground gap-1 text-xs'>
          <Icons.calendar className='size-3' />
          {dateRange.start} ~ {dateRange.end}（{dateRange.days} 天，全量展示）
        </Badge>
        <div className='ml-auto'>
          <Button size='sm' variant='outline' onClick={onExport}>
            <Icons.externalLink />
            导出 CSV
          </Button>
        </div>
      </div>

      <div className='grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5'>
        <KpiCard label='Input Tokens' value={formatNumber(totals.inputTokens)} icon='usage' />
        <KpiCard label='Output Tokens' value={formatNumber(totals.outputTokens)} icon='usage' />
        <KpiCard label='Reasoning Tokens' value={formatNumber(totals.reasoningTokens)} icon='usage' />
        <KpiCard label='Model Cost' value={formatUsd(totals.modelCostUsd)} icon='billing' />
        <KpiCard label='Runtime Seconds' value={formatHours(totals.runtimeSeconds)} icon='clock' />
        <KpiCard label='Tool Calls' value={formatNumber(totals.toolCalls)} icon='task' />
        <KpiCard label='Client Actions' value={formatNumber(totals.clientActions)} icon='effect' />
        <KpiCard label='Task Count' value={formatNumber(totals.taskCount)} icon='task' />
        <KpiCard
          label='Success Rate'
          value={`${(successRate * 100).toFixed(1)}%`}
          tone={successRate >= 0.95 ? 'success' : successRate >= 0.9 ? 'warning' : 'failure'}
          icon='badgeCheck'
        />
      </div>

      <UsageCharts daily={daily} />

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Top Host 用量汇总（按成本排序）</CardTitle>
        </CardHeader>
        <CardContent className='p-0'>
          <Table>
            <TableHeader className='bg-muted sticky top-0'>
              <TableRow>
                <TableHead>Host</TableHead>
                <TableHead className='text-right'>Tokens（In/Out/Reasoning）</TableHead>
                <TableHead className='text-right'>Cost</TableHead>
                <TableHead className='text-right'>Task Count</TableHead>
                <TableHead className='text-right'>Success Rate</TableHead>
                <TableHead className='text-right'>Runtime</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {hostSummaries.map((row) => (
                <TableRow key={row.hostAppId}>
                  <TableCell className='font-mono text-xs'>{row.hostAppId}</TableCell>
                  <TableCell className='text-right font-mono text-xs tabular-nums'>
                    {formatNumber(row.tokens)}
                  </TableCell>
                  <TableCell className='text-right font-mono text-xs tabular-nums'>
                    {formatUsd(row.costUsd)}
                  </TableCell>
                  <TableCell className='text-right font-mono text-xs tabular-nums'>
                    {formatNumber(row.taskCount)}
                  </TableCell>
                  <TableCell className='text-right font-mono text-xs tabular-nums'>
                    {(row.successRate * 100).toFixed(1)}%
                  </TableCell>
                  <TableCell className='text-muted-foreground text-right font-mono text-xs tabular-nums'>
                    {formatHours(row.runtimeSeconds)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
