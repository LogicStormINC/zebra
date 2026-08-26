'use client';

import { Alert } from '@/components/ui/alert';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { DataList } from '@/components/platform/data-list';
import { KpiCard } from '@/components/platform/kpi-card';
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime, formatDuration } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { ConformanceCheck, ConformanceRun } from '@/lib/platform/types';

const CHECK_STATUS_LABELS: Record<ConformanceCheck['status'], string> = {
  passed: '通过',
  failed: '失败',
  skipped: '跳过'
};

const CHECK_STATUS_TONES: Record<ConformanceCheck['status'], 'success' | 'failure' | 'draft'> = {
  passed: 'success',
  failed: 'failure',
  skipped: 'draft'
};

const RUN_STATUS_LABELS: Record<ConformanceRun['status'], string> = {
  running: '运行中',
  passed: '通过',
  failed: '失败'
};

/** Conformance Run 详情（PRD 16.2）：头部统计 + 按 group 分组的检查明细。 */
export function ConformanceDetail({ run }: { run: ConformanceRun }) {
  const total = run.passed + run.failed + run.skipped;
  const passRate = total === 0 ? 0 : Math.round((run.passed / total) * 100);

  const groups = run.checks.reduce<{ group: string; checks: ConformanceCheck[] }[]>(
    (acc, check) => {
      const existing = acc.find((item) => item.group === check.group);
      if (existing) {
        existing.checks.push(check);
      } else {
        acc.push({ group: check.group, checks: [check] });
      }
      return acc;
    },
    []
  );

  return (
    <div className='flex flex-col gap-6'>
      <div className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4'>
        <KpiCard
          label='通过率'
          value={`${passRate}%`}
          tone={passRate === 100 ? 'success' : passRate >= 80 ? 'warning' : 'failure'}
          icon='conformance'
          hint={`${run.passed}/${total} 项通过`}
        />
        <KpiCard label='Passed' value={run.passed} tone='success' icon='check' />
        <KpiCard
          label='Failed'
          value={run.failed}
          tone={run.failed > 0 ? 'failure' : 'default'}
          icon='close'
        />
        <KpiCard label='Skipped' value={run.skipped} icon='minus' />
      </div>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Run 信息</CardTitle>
          <CardDescription className='font-mono text-xs'>{run.id}</CardDescription>
        </CardHeader>
        <CardContent className='px-4 py-4'>
          <DataList
            columns={3}
            items={[
              { label: 'Host', value: run.hostAppId },
              { label: 'Environment', value: run.environment },
              {
                label: 'Surface',
                value: run.surface === 'backend' ? 'Backend' : 'Frontend'
              },
              { label: 'Profile Revision', value: `rev ${run.profileRevision}` },
              { label: 'Triggered By', value: <span className='font-mono text-xs'>{run.triggeredBy}</span> },
              { label: 'Started At', value: formatDateTime(run.startedAt) },
              { label: 'Duration', value: formatDuration(run.durationMs) },
              {
                label: 'Status',
                value: (
                  <StatusBadge tone={lifecycleTone(run.status)}>
                    {RUN_STATUS_LABELS[run.status]}
                  </StatusBadge>
                )
              },
              {
                label: 'Passed / Failed / Skipped',
                value: `${run.passed} / ${run.failed} / ${run.skipped}`
              }
            ]}
          />
        </CardContent>
      </Card>

      <Alert>
        <span className='text-xs'>
          敏感请求和响应只显示脱敏摘要（Request / Response
          Digest），原文不落盘、不展示，满足接入方的数据边界要求。
        </span>
      </Alert>

      <div className='flex flex-col gap-4'>
        {groups.map((group) => (
          <Card key={group.group} className='py-0'>
            <CardHeader className='border-b px-4 py-3'>
              <CardTitle className='text-sm'>{group.group}</CardTitle>
              <CardDescription>
                {group.checks.filter((check) => check.status === 'passed').length}/
                {group.checks.length} 项通过
              </CardDescription>
            </CardHeader>
            <CardContent className='p-0'>
              <Table>
                <TableHeader className='bg-muted'>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Reason Code</TableHead>
                    <TableHead>Evidence</TableHead>
                    <TableHead>Request Digest</TableHead>
                    <TableHead>Response Digest</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {group.checks.map((check) => (
                    <TableRow key={check.name}>
                      <TableCell className='font-mono text-xs'>{check.name}</TableCell>
                      <TableCell>
                        <StatusBadge tone={CHECK_STATUS_TONES[check.status]} withDot={false}>
                          {CHECK_STATUS_LABELS[check.status]}
                        </StatusBadge>
                      </TableCell>
                      <TableCell className='tabular-nums'>
                        {formatDuration(check.durationMs)}
                      </TableCell>
                      <TableCell>
                        {check.reasonCode ? (
                          <span className='font-mono text-xs font-medium text-red-600 dark:text-red-400'>
                            {check.reasonCode}
                          </span>
                        ) : (
                          <span className='text-muted-foreground'>—</span>
                        )}
                      </TableCell>
                      <TableCell className='max-w-56 truncate text-xs'>
                        {check.evidence ?? '—'}
                      </TableCell>
                      <TableCell>
                        <MonoId
                          value={`req_${run.id}_${check.name}`}
                          head={10}
                          tail={0}
                          copyable={false}
                        />
                      </TableCell>
                      <TableCell>
                        <MonoId
                          value={`res_${run.id}_${check.name}`}
                          head={10}
                          tail={0}
                          copyable={false}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
