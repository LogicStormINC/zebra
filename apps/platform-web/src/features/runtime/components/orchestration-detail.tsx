'use client';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { DataList } from '@/components/platform/data-list';
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { TASK_STATUS_LABELS, taskStatusTone } from '@/lib/platform/status';
import { formatDateTime, formatNumber, formatUsd } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import { OrchestrationDag } from './orchestration-dag';
import type { OrchestrationRun, ReleaseGate } from '@/lib/platform/types';

const GATE_TONES: Record<string, 'success' | 'failure' | 'waiting' | 'draft'> = {
  passed: 'success',
  failed: 'failure',
  pending: 'waiting',
  not_required: 'draft'
};

/** Orchestration 详情：Header + DAG + Completion Gate / Plan Revision 卡 + 节点表。 */
export function OrchestrationDetail({
  run,
  gates
}: {
  run: OrchestrationRun;
  gates: ReleaseGate[];
}) {
  const completionGates = run.nodes.filter((node) => node.gate === 'completion');
  const pendingGates = gates.filter((gate) => gate.status === 'pending');

  return (
    <div className='flex flex-col gap-4 p-4 md:px-6'>
      <div className='text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs'>
        <span className='flex items-center gap-1'>
          Task{' '}
          <Link href={`/runtime/tasks/${run.taskId}`} className='text-primary font-mono hover:underline'>
            {run.taskId}
          </Link>
        </span>
        <span>
          Strategy <Badge variant='outline'>{run.strategy}</Badge>
        </span>
        <span>
          Status{' '}
          <StatusBadge tone={taskStatusTone(run.status)}>
            {TASK_STATUS_LABELS[run.status] ?? run.status}
          </StatusBadge>
        </span>
        <span>Tokens {formatNumber(run.totalTokens)}</span>
        <span>Cost {formatUsd(run.totalCostUsd)}</span>
        <span>Created {formatDateTime(run.createdAt)}</span>
      </div>

      <OrchestrationDag run={run} />

      <div className='grid grid-cols-1 gap-3 lg:grid-cols-2'>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='flex items-center gap-2 text-sm'>
              <Icons.gate className='size-4' />
              Completion Gate
            </CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            {completionGates.length === 0 ? (
              <p className='text-muted-foreground text-sm'>该计划没有 completion gate 节点</p>
            ) : (
              <ul className='space-y-2 text-sm'>
                {completionGates.map((node) => (
                  <li key={node.id} className='flex items-center justify-between gap-2'>
                    <span>{node.label}</span>
                    <StatusBadge tone={taskStatusTone(node.status)}>
                      {TASK_STATUS_LABELS[node.status] ?? node.status}
                    </StatusBadge>
                  </li>
                ))}
              </ul>
            )}
            {pendingGates.length > 0 && (
              <div className='border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-400 mt-3 rounded-lg border p-2.5 text-xs'>
                {pendingGates.length} 个发布门禁待评估：{pendingGates.map((gate) => gate.gate).join('、')}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>Plan Revision</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            <DataList
              columns={2}
              items={[
                { label: 'Revision', value: `rev ${run.planRevision}` },
                { label: 'Run', value: <MonoId value={run.runRef} /> },
                { label: 'Strategy', value: run.strategy },
                { label: 'Nodes', value: `${run.nodes.length} 个` },
                { label: 'Total Tokens', value: formatNumber(run.totalTokens) },
                { label: 'Total Cost', value: formatUsd(run.totalCostUsd) }
              ]}
            />
          </CardContent>
        </Card>
      </div>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Node</TableHead>
              <TableHead>Label</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Child Task</TableHead>
              <TableHead>Depends On</TableHead>
              <TableHead>Budget Tokens</TableHead>
              <TableHead>Gate</TableHead>
              <TableHead>Evidence</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {run.nodes.map((node) => (
              <TableRow key={node.id}>
                <TableCell className='font-mono text-xs'>{node.id}</TableCell>
                <TableCell className='font-medium'>{node.label}</TableCell>
                <TableCell>
                  <Badge variant='outline'>{node.role}</Badge>
                </TableCell>
                <TableCell>
                  {node.childTaskId ? (
                    <Link href={`/runtime/tasks/${node.childTaskId}`} className='text-primary font-mono text-xs hover:underline'>
                      {node.childTaskId}
                    </Link>
                  ) : (
                    <span className='text-muted-foreground text-xs'>—</span>
                  )}
                </TableCell>
                <TableCell className='font-mono text-xs'>
                  {node.dependsOn.length === 0 ? '—' : node.dependsOn.join(', ')}
                </TableCell>
                <TableCell className='tabular-nums'>{formatNumber(node.budgetTokens)}</TableCell>
                <TableCell>
                  {node.gate ? (
                    <StatusBadge tone={GATE_TONES[node.gate === 'completion' ? 'pending' : node.gate] ?? 'waiting'} withDot={false}>
                      {node.gate}
                    </StatusBadge>
                  ) : (
                    <span className='text-muted-foreground text-xs'>—</span>
                  )}
                </TableCell>
                <TableCell className='text-muted-foreground max-w-[200px] truncate text-sm'>
                  {node.evidence ?? '—'}
                </TableCell>
                <TableCell>
                  <StatusBadge tone={taskStatusTone(node.status)}>
                    {TASK_STATUS_LABELS[node.status] ?? node.status}
                  </StatusBadge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
