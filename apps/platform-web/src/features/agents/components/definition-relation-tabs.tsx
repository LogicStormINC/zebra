'use client';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { EmptyState } from '@/components/platform/empty-state';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import { formatUsd } from '@/lib/platform/format';
import type { DefinitionDetailData } from './definition-detail-data';

const BINDING_STATUS_LABELS: Record<string, string> = {
  active: '生效中',
  canary: '灰度',
  'rolled-back': '已回滚',
  draft: '草稿'
};

/** Evaluation Tab：该 Definition 各 Release 的评测记录。 */
export function DefinitionEvaluationTab({ data }: { data: DefinitionDetailData }) {
  if (data.evaluations.length === 0) {
    return (
      <EmptyState
        icon='evaluation'
        title='暂无评测记录'
        description='为该 Definition 的 Release 绑定 Evaluation Profile 后，发布前会自动运行回归评测'
      />
    );
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>评测</TableHead>
            <TableHead>Release</TableHead>
            <TableHead>Dataset</TableHead>
            <TableHead>Quality</TableHead>
            <TableHead>Tool Accuracy</TableHead>
            <TableHead>Structured Output</TableHead>
            <TableHead>Latency P95</TableHead>
            <TableHead>Cost / Run</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created At</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.evaluations.map((evaluation) => (
            <TableRow key={evaluation.id}>
              <TableCell className='font-medium'>{evaluation.name}</TableCell>
              <TableCell className='font-mono text-xs'>{evaluation.agentReleaseId}</TableCell>
              <TableCell className='font-mono text-xs'>{evaluation.dataset}</TableCell>
              <TableCell className='tabular-nums'>{evaluation.qualityScore.toFixed(2)}</TableCell>
              <TableCell className='tabular-nums'>{evaluation.toolAccuracy.toFixed(2)}</TableCell>
              <TableCell className='tabular-nums'>{evaluation.structuredOutputPassRate.toFixed(2)}</TableCell>
              <TableCell className='tabular-nums'>{(evaluation.latencyP95Ms / 1000).toFixed(1)}s</TableCell>
              <TableCell className='tabular-nums'>{formatUsd(evaluation.costUsdPerRun)}</TableCell>
              <TableCell>
                <StatusBadge tone={lifecycleTone(evaluation.status)}>{evaluation.status}</StatusBadge>
              </TableCell>
              <TableCell className='text-sm'>{formatDateTime(evaluation.createdAt)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Host Bindings Tab：使用该 Definition Release 的 Namespace Binding。 */
export function DefinitionBindingsTab({ data }: { data: DefinitionDetailData }) {
  if (data.bindings.length === 0) {
    return (
      <EmptyState
        icon='binding'
        title='暂无 Host Binding 使用该 Definition'
        description='Host 在接入中心将 Namespace 绑定到某个 Agent Release 后，会出现在这里'
      />
    );
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Binding</TableHead>
            <TableHead>Host</TableHead>
            <TableHead>Namespace</TableHead>
            <TableHead>Environment</TableHead>
            <TableHead>Agent Release</TableHead>
            <TableHead>Expected Revision</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Updated At</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.bindings.map((binding) => (
            <TableRow key={binding.id}>
              <TableCell className='font-mono text-xs'>{binding.id}</TableCell>
              <TableCell>
                <Link href={`/integrations/hosts/${binding.hostAppId}`} className='text-primary text-sm hover:underline'>
                  {binding.hostAppId}
                </Link>
              </TableCell>
              <TableCell className='font-mono text-xs'>{binding.namespace}</TableCell>
              <TableCell>
                <Badge variant='outline' className='text-xs'>{binding.environment}</Badge>
              </TableCell>
              <TableCell className='font-mono text-xs'>{binding.agentReleaseId}</TableCell>
              <TableCell className='tabular-nums'>rev {binding.expectedRevision}</TableCell>
              <TableCell>
                <StatusBadge tone={lifecycleTone(binding.status === 'canary' ? 'running' : binding.status)}>
                  {BINDING_STATUS_LABELS[binding.status] ?? binding.status}
                </StatusBadge>
              </TableCell>
              <TableCell className='text-sm'>{formatDateTime(binding.updatedAt)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

const ACTOR_TYPE_LABELS: Record<string, string> = {
  operator: '操作员',
  system: '系统',
  agent: 'Agent'
};

/** Audit Tab：resourceId 与该 Definition 及其 Release 相关的审计记录。 */
export function DefinitionAuditTab({ data }: { data: DefinitionDetailData }) {
  if (data.auditEntries.length === 0) {
    return (
      <EmptyState
        icon='audit'
        title='暂无相关审计记录'
        description='该 Definition 及其 Release 的发布、撤销等操作会写入 Audit Log'
      />
    );
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Action</TableHead>
            <TableHead>Resource</TableHead>
            <TableHead>Result</TableHead>
            <TableHead>Reason</TableHead>
            <TableHead>Correlation</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.auditEntries.map((entry) => (
            <TableRow key={entry.id}>
              <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(entry.timestamp)}</TableCell>
              <TableCell className='text-sm'>
                <Badge variant='outline' className='mr-1.5 text-xs'>
                  {ACTOR_TYPE_LABELS[entry.actorType] ?? entry.actorType}
                </Badge>
                {entry.actor}
              </TableCell>
              <TableCell className='font-mono text-xs'>{entry.action}</TableCell>
              <TableCell className='font-mono text-xs'>
                {entry.resourceType}/{entry.resourceId}
              </TableCell>
              <TableCell>
                <StatusBadge tone={lifecycleTone(entry.result === 'succeeded' ? 'published' : entry.result)}>
                  {entry.result === 'succeeded' ? '成功' : entry.result === 'denied' ? '被拒绝' : '失败'}
                </StatusBadge>
              </TableCell>
              <TableCell className='text-muted-foreground max-w-[240px] truncate text-sm'>
                {entry.reason ?? '—'}
              </TableCell>
              <TableCell className='font-mono text-xs'>{entry.correlationId}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
