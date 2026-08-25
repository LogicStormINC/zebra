'use client';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { KpiCard } from '@/components/platform/kpi-card';
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { lifecycleTone } from '@/lib/platform/status';
import { formatBytes, formatDateTime, formatNumber, formatUsd } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import type { Artifact, AuditEntry } from '@/lib/platform/types';
import type { TaskDetailData } from './task-detail-data';

const KIND_LABELS: Record<Artifact['kind'], string> = {
  patch: 'Patch',
  report: '报告',
  screenshot: '截图',
  log: '日志',
  export: '导出',
  diagnostic_bundle: '诊断包'
};

/** Artifacts Tab：产物表 + 下载（演示 toast）。 */
export function TaskArtifactsTab({ artifacts }: { artifacts: Artifact[] }) {
  if (artifacts.length === 0) {
    return (
      <EmptyState
        icon='artifact'
        title='该 Task 无产物'
        description='报告、补丁、导出文件等产物按 digest 存档，可随时下载校验'
      />
    );
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Kind</TableHead>
            <TableHead>Bytes</TableHead>
            <TableHead>Digest</TableHead>
            <TableHead>Created At</TableHead>
            <TableHead className='text-right'>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {artifacts.map((artifact) => (
            <TableRow key={artifact.id}>
              <TableCell className='font-medium'>{artifact.name}</TableCell>
              <TableCell>
                <Badge variant='outline'>{KIND_LABELS[artifact.kind] ?? artifact.kind}</Badge>
              </TableCell>
              <TableCell className='tabular-nums'>{formatBytes(artifact.bytes)}</TableCell>
              <TableCell>
                <MonoId value={artifact.digest} />
              </TableCell>
              <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(artifact.createdAt)}</TableCell>
              <TableCell className='text-right'>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() =>
                    toast.success('开始下载（演示）', { description: `${artifact.name} · ${formatBytes(artifact.bytes)}` })
                  }
                >
                  <Icons.externalLink className='size-4' />
                  下载
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Usage Tab：tokens / cost 聚合 + 模型成本明细。 */
export function TaskUsageTab({ data }: { data: TaskDetailData }) {
  const { task, modelCalls } = data;
  const inputTokens = modelCalls.reduce((sum, call) => sum + call.inputTokens, 0);
  const outputTokens = modelCalls.reduce((sum, call) => sum + call.outputTokens, 0);
  const reasoningTokens = modelCalls.reduce((sum, call) => sum + call.reasoningTokens, 0);
  const modelCost = modelCalls.reduce((sum, call) => sum + call.costUsd, 0);

  return (
    <div className='flex flex-col gap-4'>
      <div className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
        <KpiCard label='Model Tokens（Task 口径）' value={formatNumber(task.modelTokens)} icon='usage' />
        <KpiCard
          label='Tokens（Call 口径）'
          value={formatNumber(inputTokens + outputTokens + reasoningTokens)}
          icon='quota'
          hint={`入 ${formatNumber(inputTokens)} / 出 ${formatNumber(outputTokens)} / 推理 ${formatNumber(reasoningTokens)}`}
        />
        <KpiCard label='Cost（Task 口径）' value={formatUsd(task.costUsd)} icon='billing' />
        <KpiCard
          label='Cost（Call 口径）'
          value={formatUsd(modelCost)}
          icon='billing'
          hint={`${modelCalls.length} 次模型调用`}
        />
      </div>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>模型成本明细</CardTitle>
        </CardHeader>
        <CardContent className='p-0'>
          {modelCalls.length === 0 ? (
            <p className='text-muted-foreground p-4 text-sm'>暂无模型调用</p>
          ) : (
            <Table>
              <TableHeader className='bg-muted'>
                <TableRow>
                  <TableHead>Call</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Resolved Model</TableHead>
                  <TableHead>Tokens（入 / 出 / 推理）</TableHead>
                  <TableHead>Latency</TableHead>
                  <TableHead>Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {modelCalls.map((call) => (
                  <TableRow key={call.id}>
                    <TableCell>
                      <MonoId value={call.id} copyable={false} />
                    </TableCell>
                    <TableCell>
                      <Badge variant='outline'>{call.role}</Badge>
                    </TableCell>
                    <TableCell className='font-mono text-xs'>{call.resolvedModel}</TableCell>
                    <TableCell className='tabular-nums text-xs'>
                      {formatNumber(call.inputTokens)} / {formatNumber(call.outputTokens)} /{' '}
                      {formatNumber(call.reasoningTokens)}
                    </TableCell>
                    <TableCell className='tabular-nums'>
                      {`${(call.latencyMs / 1000).toFixed(1)}s`}
                    </TableCell>
                    <TableCell className='tabular-nums'>{formatUsd(call.costUsd)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

const ACTOR_TYPE_LABELS: Record<string, string> = {
  operator: '操作员',
  system: '系统',
  agent: 'Agent'
};

/** Audit Tab：与该 Task 相关的审计记录（resourceId / correlationId 命中）。 */
export function TaskAuditTab({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) {
    return (
      <EmptyState
        icon='audit'
        title='暂无相关审计记录'
        description='取消、挂起、审批等运维操作会以 correlationId 关联写入 Audit Log'
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
          {entries.map((entry) => (
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
