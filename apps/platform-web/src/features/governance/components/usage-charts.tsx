'use client';

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatNumber, formatUsd } from '@/lib/platform/format';
import type { UsageRecord } from '@/lib/platform/types';

export type DailyUsage = {
  date: string;
  inputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  modelCostUsd: number;
};

const TOOLTIP_STYLE = {
  background: 'var(--popover)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  fontSize: 12
} as const;

/** Usage 与成本图表（PRD 22.2）：Token 堆叠面积图 + 成本趋势折线图。 */
export function UsageCharts({ daily }: { daily: DailyUsage[] }) {
  return (
    <div className='grid grid-cols-1 gap-4 xl:grid-cols-2'>
      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Token 用量（按天，Input / Output / Reasoning 堆叠）</CardTitle>
        </CardHeader>
        <CardContent className='p-2 pt-4'>
          <ResponsiveContainer width='100%' height={260}>
            <AreaChart data={daily} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id='inputFill' x1='0' y1='0' x2='0' y2='1'>
                  <stop offset='0%' stopColor='var(--chart-1)' stopOpacity={0.45} />
                  <stop offset='100%' stopColor='var(--chart-1)' stopOpacity={0.05} />
                </linearGradient>
                <linearGradient id='outputFill' x1='0' y1='0' x2='0' y2='1'>
                  <stop offset='0%' stopColor='var(--chart-2)' stopOpacity={0.45} />
                  <stop offset='100%' stopColor='var(--chart-2)' stopOpacity={0.05} />
                </linearGradient>
                <linearGradient id='reasoningFill' x1='0' y1='0' x2='0' y2='1'>
                  <stop offset='0%' stopColor='var(--chart-3)' stopOpacity={0.45} />
                  <stop offset='100%' stopColor='var(--chart-3)' stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray='3 3' stroke='var(--border)' vertical={false} />
              <XAxis dataKey='date' tick={{ fontSize: 11 }} stroke='var(--muted-foreground)' />
              <YAxis
                tick={{ fontSize: 11 }}
                stroke='var(--muted-foreground)'
                width={44}
                tickFormatter={(value: number) => formatNumber(value)}
              />
              <Tooltip
                formatter={(value: unknown, name: unknown) => {
                  const numeric = typeof value === 'number' ? value : Number(value ?? 0);
                  const label = String(name ?? '');
                  return [label === '成本' ? formatUsd(numeric) : formatNumber(numeric), label];
                }}
                contentStyle={TOOLTIP_STYLE}
              />
              <Area
                type='monotone'
                stackId='tokens'
                dataKey='inputTokens'
                name='Input'
                stroke='var(--chart-1)'
                strokeWidth={2}
                fill='url(#inputFill)'
              />
              <Area
                type='monotone'
                stackId='tokens'
                dataKey='outputTokens'
                name='Output'
                stroke='var(--chart-2)'
                strokeWidth={2}
                fill='url(#outputFill)'
              />
              <Area
                type='monotone'
                stackId='tokens'
                dataKey='reasoningTokens'
                name='Reasoning'
                stroke='var(--chart-3)'
                strokeWidth={2}
                fill='url(#reasoningFill)'
              />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>模型成本趋势（按天，USD）</CardTitle>
        </CardHeader>
        <CardContent className='p-2 pt-4'>
          <ResponsiveContainer width='100%' height={260}>
            <LineChart data={daily} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray='3 3' stroke='var(--border)' vertical={false} />
              <XAxis dataKey='date' tick={{ fontSize: 11 }} stroke='var(--muted-foreground)' />
              <YAxis
                tick={{ fontSize: 11 }}
                stroke='var(--muted-foreground)'
                width={52}
                tickFormatter={(value: number) => formatUsd(value)}
              />
              <Tooltip
                formatter={(value: unknown, name: unknown) => {
                  const numeric = typeof value === 'number' ? value : Number(value ?? 0);
                  return [String(name ?? '') === '成本' ? formatUsd(numeric) : formatNumber(numeric), String(name ?? '')];
                }}
                contentStyle={TOOLTIP_STYLE}
              />
              <Line
                type='monotone'
                dataKey='modelCostUsd'
                name='成本'
                stroke='var(--chart-4)'
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}

export function aggregateDaily(records: UsageRecord[]): DailyUsage[] {
  const byDate = new Map<string, DailyUsage>();
  for (const record of records) {
    const existing = byDate.get(record.date) ?? {
      date: record.date,
      inputTokens: 0,
      outputTokens: 0,
      reasoningTokens: 0,
      modelCostUsd: 0
    };
    existing.inputTokens += record.inputTokens;
    existing.outputTokens += record.outputTokens;
    existing.reasoningTokens += record.reasoningTokens;
    existing.modelCostUsd = Number((existing.modelCostUsd + record.modelCostUsd).toFixed(4));
    byDate.set(record.date, existing);
  }
  return [...byDate.values()].toSorted((a, b) => a.date.localeCompare(b.date));
}
