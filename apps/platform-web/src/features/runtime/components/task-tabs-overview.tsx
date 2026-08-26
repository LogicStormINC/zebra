'use client';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataList } from '@/components/platform/data-list';
import { DigestTag, MonoId } from '@/components/platform/mono-id';
import { EmptyState } from '@/components/platform/empty-state';
import { KpiCard } from '@/components/platform/kpi-card';
import { StatusBadge } from '@/components/platform/status-badge';
import {
  CLIENT_BINDING_STATUS_LABELS,
  LIFECYCLE_STATUS_LABELS,
  lifecycleTone,
  TASK_STATUS_LABELS,
  taskStatusTone
} from '@/lib/platform/status';
import { formatDateTime, formatNumber, formatUsd, relativeTime } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import type { PolicyRecord } from '@/lib/platform/types';
import { TASK_BUDGET_TOKENS, TASK_BUDGET_USD, type TaskDetailData } from './task-detail-data';

/** Overview Tab（PRD 18.5）：状态卡 + 快照摘要 + 最近活动 + 预算。 */
export function TaskOverviewTab({ data }: { data: TaskDetailData }) {
  const { task, events, toolCalls, clientEffects, clientRunBindings } = data;

  const lastErrorEvent = events
    .toReversed()
    .find(
      (event) =>
        event.type === 'task_failed' ||
        event.summary.includes('失败') ||
        event.summary.includes('超时')
    );
  const lastTool = toolCalls[toolCalls.length - 1];
  const lastClientEffect = clientEffects
    .toSorted((a, b) => a.createdAt.localeCompare(b.createdAt))
    .pop();

  return (
    <div className='flex flex-col gap-4'>
      <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>当前状态</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            <DataList
              columns={2}
              items={[
                {
                  label: 'Status',
                  value: (
                    <StatusBadge tone={taskStatusTone(task.status)}>
                      {TASK_STATUS_LABELS[task.status]}
                    </StatusBadge>
                  )
                },
                {
                  label: 'Current Segment',
                  value: <span className='font-mono'>{task.currentSegment}</span>
                },
                { label: '等待原因', value: task.waitReason ?? '—' },
                {
                  label: 'Subagents',
                  value:
                    task.subagentCount > 0 ? `${task.subagentCount} 个（/runtime/subagents）` : '无'
                },
                { label: 'Has Client', value: task.hasClient ? '是' : '否' },
                {
                  label: 'Has Uncertain Effect',
                  value: task.hasUncertainEffect ? '是（需要对账）' : '否'
                }
              ]}
            />
          </CardContent>
        </Card>

        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>AgentDefinition Snapshot</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            <DataList
              columns={2}
              items={[
                { label: 'Agent Release', value: <MonoId value={task.agentReleaseId} /> },
                {
                  label: 'Release Digest',
                  value: data.release ? <DigestTag value={data.release.digest} /> : '—'
                },
                { label: 'Agent Name', value: task.agentName },
                {
                  label: 'Memory Policy',
                  value: data.memoryPolicy?.name ?? '未启用'
                }
              ]}
            />
          </CardContent>
        </Card>
      </div>

      <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>Host Capability Snapshot</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            {data.host ? (
              <DataList
                columns={2}
                items={[
                  { label: 'Host', value: `${data.host.name}（${data.host.appId}）` },
                  {
                    label: 'Connector Revision',
                    value: data.host.connectorRevision ? `rev ${data.host.connectorRevision}` : '—'
                  },
                  {
                    label: 'Backend Manifest',
                    value: data.manifest ? (
                      <span className='flex items-center gap-1.5'>
                        <MonoId value={data.manifest.id} copyable={false} /> rev{' '}
                        {data.manifest.revision}
                      </span>
                    ) : (
                      '—'
                    )
                  },
                  {
                    label: 'Manifest Digest',
                    value: data.manifest ? <DigestTag value={data.manifest.digest} /> : '—'
                  }
                ]}
              />
            ) : (
              <p className='text-muted-foreground text-sm'>未找到 Host 快照</p>
            )}
          </CardContent>
        </Card>

        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>Frontend Binding</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            {clientRunBindings.length > 0 ? (
              <div className='flex flex-col gap-3'>
                {clientRunBindings.map((binding) => (
                  <DataList
                    key={binding.id}
                    columns={2}
                    items={[
                      { label: 'Client Run Binding', value: <MonoId value={binding.id} /> },
                      { label: 'Run', value: <span className='font-mono'>{binding.runId}</span> },
                      {
                        label: 'Client Session',
                        value: <span className='font-mono'>{binding.clientSessionId}</span>
                      },
                      {
                        label: 'Snapshot Digest',
                        value: <DigestTag value={binding.snapshotDigest} />
                      },
                      {
                        label: 'Status',
                        value: (
                          <StatusBadge tone={lifecycleTone(binding.status)}>
                            {CLIENT_BINDING_STATUS_LABELS[binding.status] ?? binding.status}
                          </StatusBadge>
                        )
                      },
                      { label: 'Created At', value: formatDateTime(binding.createdAt) }
                    ]}
                  />
                ))}
              </div>
            ) : (
              <p className='text-muted-foreground text-sm'>该 Task 未绑定前端会话</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className='grid grid-cols-1 gap-3 lg:grid-cols-3'>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>最近错误</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            {lastErrorEvent || (task.status === 'failed' && task.waitReason) ? (
              <p className='text-destructive text-sm'>
                {lastErrorEvent?.summary ?? task.waitReason}
              </p>
            ) : (
              <p className='flex items-center gap-2 text-sm'>
                <Icons.check className='text-emerald-600 size-4' />
                无错误记录
              </p>
            )}
          </CardContent>
        </Card>

        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>最近 Tool</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            {lastTool ? (
              <div className='space-y-1 text-sm'>
                <p className='font-mono text-xs'>{lastTool.toolName}</p>
                <p className='text-muted-foreground text-xs'>
                  {lastTool.executionLocation} · {lastTool.status} · arguments{' '}
                  <span className='font-mono'>{lastTool.argumentsDigest.slice(0, 10)}</span>
                </p>
              </div>
            ) : (
              <p className='text-muted-foreground text-sm'>尚未调用工具</p>
            )}
          </CardContent>
        </Card>

        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>最近 Client Effect</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            {lastClientEffect ? (
              <div className='space-y-1 text-sm'>
                <p className='font-mono text-xs'>{lastClientEffect.action}</p>
                <p className='text-muted-foreground text-xs'>
                  {lastClientEffect.status} · expected ui rev {lastClientEffect.expectedRevision} ·{' '}
                  {relativeTime(lastClientEffect.createdAt)}
                </p>
              </div>
            ) : (
              <p className='text-muted-foreground text-sm'>无 Client Effect</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
        <KpiCard
          label='Model Tokens'
          value={formatNumber(task.modelTokens)}
          icon='usage'
          hint={`上限 ${formatNumber(TASK_BUDGET_TOKENS)}`}
        />
        <KpiCard
          label='Cost'
          value={formatUsd(task.costUsd)}
          icon='billing'
          hint={`上限 ${formatUsd(TASK_BUDGET_USD)}`}
        />
        <KpiCard
          label='Tokens 余量'
          value={`${Math.round((1 - task.modelTokens / TASK_BUDGET_TOKENS) * 100)}%`}
          tone={task.modelTokens > TASK_BUDGET_TOKENS * 0.8 ? 'warning' : 'default'}
          icon='quota'
        />
        <KpiCard
          label='Cost 余量'
          value={`${Math.round((1 - task.costUsd / TASK_BUDGET_USD) * 100)}%`}
          tone={task.costUsd > TASK_BUDGET_USD * 0.8 ? 'warning' : 'default'}
          icon='quota'
        />
      </div>

      {task.orchestrationRunRef && (
        <p className='text-muted-foreground text-xs'>
          编排运行：
          <Link
            href={`/runtime/orchestrations/${task.orchestrationRunRef}`}
            className='text-primary hover:underline'
          >
            {task.orchestrationRunRef}
          </Link>
        </p>
      )}
    </div>
  );
}

/** Memory Tab：未启用时 EmptyState，否则展示策略摘要。 */
export function TaskMemoryTab({ memoryPolicy }: { memoryPolicy?: PolicyRecord }) {
  if (!memoryPolicy) {
    return (
      <EmptyState
        icon='agent'
        title='该 Task 未启用 Memory Policy'
        description='Definition 配置 Memory Policy Ref 后，跨 Attempt 的记忆读写才会被记录'
      />
    );
  }
  return (
    <Card className='py-0'>
      <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
        <CardTitle className='text-sm'>{memoryPolicy.name}</CardTitle>
        <StatusBadge tone={lifecycleTone(memoryPolicy.status)}>
          {LIFECYCLE_STATUS_LABELS[memoryPolicy.status] ?? memoryPolicy.status}
        </StatusBadge>
      </CardHeader>
      <CardContent className='p-4'>
        <DataList
          columns={3}
          items={[
            { label: 'Policy ID', value: <MonoId value={memoryPolicy.id} copyable={false} /> },
            { label: 'Scope', value: <Badge variant='outline'>{memoryPolicy.scope}</Badge> },
            { label: 'Revision', value: `rev ${memoryPolicy.revision}` },
            { label: 'Digest', value: <DigestTag value={memoryPolicy.digest} /> },
            { label: 'Updated By', value: memoryPolicy.updatedBy },
            { label: 'Updated At', value: formatDateTime(memoryPolicy.updatedAt) }
          ]}
        />
      </CardContent>
    </Card>
  );
}
