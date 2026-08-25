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
import { overviewTrend } from '@/lib/platform/mock/overview';
import { formatNumber, formatUsd } from '@/lib/platform/format';

/** 图表第二行（PRD 9.2）：Task 趋势、成功率、Token 与成本。 */
export function OverviewCharts() {
  const trend = overviewTrend();

  return (
    <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Task 趋势（近 14 天）</CardTitle>
        </CardHeader>
        <CardContent className='p-2 pt-4'>
          <ResponsiveContainer width='100%' height={220}>
            <AreaChart data={trend} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id='taskFill' x1='0' y1='0' x2='0' y2='1'>
                  <stop offset='0%' stopColor='var(--primary)' stopOpacity={0.35} />
                  <stop offset='100%' stopColor='var(--primary)' stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray='3 3' stroke='var(--border)' vertical={false} />
              <XAxis dataKey='date' tick={{ fontSize: 11 }} stroke='var(--muted-foreground)' />
              <YAxis tick={{ fontSize: 11 }} stroke='var(--muted-foreground)' width={36} />
              <Tooltip
                contentStyle={{
                  background: 'var(--popover)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  fontSize: 12
                }}
              />
              <Area
                type='monotone'
                dataKey='tasks'
                name='Task 数'
                stroke='var(--primary)'
                strokeWidth={2}
                fill='url(#taskFill)'
              />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>成功率与 Token / 成本趋势</CardTitle>
        </CardHeader>
        <CardContent className='p-2 pt-4'>
          <ResponsiveContainer width='100%' height={220}>
            <LineChart data={trend} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray='3 3' stroke='var(--border)' vertical={false} />
              <XAxis dataKey='date' tick={{ fontSize: 11 }} stroke='var(--muted-foreground)' />
              <YAxis yAxisId='left' tick={{ fontSize: 11 }} stroke='var(--muted-foreground)' width={36} />
              <YAxis
                yAxisId='right'
                orientation='right'
                tick={{ fontSize: 11 }}
                stroke='var(--muted-foreground)'
                width={44}
                tickFormatter={(value: number) => formatNumber(value)}
              />
              <Tooltip
                formatter={(value, name) => {
                  const numeric = typeof value === 'number' ? value : Number(value ?? 0);
                  const label = String(name ?? '');
                  if (label === '成功率') return `${(numeric * 100).toFixed(1)}%`;
                  if (label === '成本') return formatUsd(numeric);
                  return formatNumber(numeric);
                }}
                contentStyle={{
                  background: 'var(--popover)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  fontSize: 12
                }}
              />
              <Line
                yAxisId='left'
                type='monotone'
                dataKey='successRate'
                name='成功率'
                stroke='var(--chart-2)'
                strokeWidth={2}
                dot={false}
              />
              <Line
                yAxisId='right'
                type='monotone'
                dataKey='tokens'
                name='Token'
                stroke='var(--chart-1)'
                strokeWidth={2}
                dot={false}
              />
              <Line
                yAxisId='left'
                type='monotone'
                dataKey='costUsd'
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
