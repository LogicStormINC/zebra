'use client';

import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Icons } from '@/components/icons';
import { KpiCard } from '@/components/platform/kpi-card';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime, formatNumber, formatUsd } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type {
  AuditEntry,
  ConformanceRun,
  NamespaceBinding,
  UsageRecord
} from '@/lib/platform/types';
import { BINDING_STATUS_LABELS, ENVIRONMENT_LABELS } from '../lib/labels';

/** Namespace Bindings 面板（PRD 15）。 */
export function HostBindingsTab({ bindings }: { bindings: NamespaceBinding[] }) {
  if (bindings.length === 0) {
    return (
      <Card className='py-0'>
        <CardContent className='text-muted-foreground p-4 text-sm'>
          该 Host 尚无 Namespace Binding，前往{' '}
          <Link href='/integrations/bindings' className='text-primary underline underline-offset-2'>
            Namespace Binding 列表
          </Link>{' '}
          创建。
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className='py-0'>
      <CardHeader className='border-b px-4 py-3'>
        <CardTitle className='text-sm'>Namespace Bindings（{bindings.length}）</CardTitle>
      </CardHeader>
      <CardContent className='p-0'>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Namespace</TableHead>
              <TableHead>Environment</TableHead>
              <TableHead>Connector Rev</TableHead>
              <TableHead>Manifest Rev</TableHead>
              <TableHead>Agent Release</TableHead>
              <TableHead>Expected Rev</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {bindings.map((binding) => (
              <TableRow key={binding.id}>
                <TableCell className='font-mono text-xs'>{binding.namespace}</TableCell>
                <TableCell>{ENVIRONMENT_LABELS[binding.environment]}</TableCell>
                <TableCell className='tabular-nums'>rev {binding.connectorRevision}</TableCell>
                <TableCell className='tabular-nums'>rev {binding.manifestRevision}</TableCell>
                <TableCell>
                  <Link
                    href='/agents/releases'
                    className='text-primary font-mono text-xs hover:underline'
                  >
                    {binding.agentReleaseId}
                  </Link>
                </TableCell>
                <TableCell className='tabular-nums'>{binding.expectedRevision}</TableCell>
                <TableCell>
                  <StatusBadge tone={lifecycleTone(binding.status === 'active' ? 'active' : binding.status === 'canary' ? 'running' : 'pending')} withDot={false}>
                    {BINDING_STATUS_LABELS[binding.status]}
                  </StatusBadge>
                </TableCell>
                <TableCell className='text-muted-foreground text-xs'>
                  {formatDateTime(binding.updatedAt)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

/** Agent Bindings 面板：从 Namespace Binding 推导绑定的 Agent Release。 */
export function HostAgentBindingsTab({
  bindings,
  releaseNames
}: {
  bindings: NamespaceBinding[];
  releaseNames: Record<string, string>;
}) {
  const releases = Array.from(new Set(bindings.map((binding) => binding.agentReleaseId)));

  return (
    <Card className='py-0'>
      <CardHeader className='border-b px-4 py-3'>
        <CardTitle className='text-sm'>绑定的 Agent Release</CardTitle>
      </CardHeader>
      <CardContent className='divide-y p-0'>
        {releases.length === 0 ? (
          <p className='text-muted-foreground px-4 py-3 text-sm'>尚无绑定的 Agent Release。</p>
        ) : (
          releases.map((releaseId) => (
            <div key={releaseId} className='flex items-center justify-between gap-3 px-4 py-3'>
              <div className='min-w-0'>
                <p className='truncate font-mono text-sm font-medium'>{releaseId}</p>
                <p className='text-muted-foreground truncate text-xs'>
                  {releaseNames[releaseId] ?? '未知 Agent'} · 被 {bindings.filter((b) => b.agentReleaseId === releaseId).length} 个 namespace 绑定
                </p>
              </div>
              <Button variant='outline' size='sm' render={<Link href='/agents/releases' aria-label='查看 Releases' />}>
                查看 Releases
                <Icons.chevronRight className='size-3.5' />
              </Button>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

/** Conformance 面板（PRD 19）。 */
export function HostConformanceTab({ runs }: { runs: ConformanceRun[] }) {
  return (
    <Card className='py-0'>
      <CardHeader className='border-b px-4 py-3'>
        <CardTitle className='text-sm'>Conformance Runs（{runs.length}）</CardTitle>
      </CardHeader>
      <CardContent className='divide-y p-0'>
        {runs.length === 0 ? (
          <p className='text-muted-foreground px-4 py-3 text-sm'>暂无 Conformance 记录。</p>
        ) : (
          runs.map((run) => (
            <div key={run.id} className='flex items-center justify-between gap-3 px-4 py-3'>
              <div className='min-w-0'>
                <p className='truncate text-sm font-medium'>
                  <span className='font-mono text-xs'>{run.id}</span>
                </p>
                <p className='text-muted-foreground truncate text-xs'>
                  {run.surface === 'backend' ? 'Backend' : 'Frontend'} · profile rev {run.profileRevision} ·{' '}
                  {formatDateTime(run.startedAt)} · {run.triggeredBy}
                </p>
              </div>
              <div className='flex items-center gap-2'>
                <span className='text-muted-foreground text-xs tabular-nums'>
                  {run.passed} pass / {run.failed} fail / {run.skipped} skip
                </span>
                <StatusBadge tone={lifecycleTone(run.status)}>
                  {run.status === 'passed' ? '通过' : run.status === 'failed' ? '未通过' : '运行中'}
                </StatusBadge>
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

/** Usage 面板：该 Host 的用量聚合（PRD 22）。 */
export function HostUsageTab({ usage }: { usage: UsageRecord[] }) {
  const totalInput = usage.reduce((sum, record) => sum + record.inputTokens, 0);
  const totalOutput = usage.reduce((sum, record) => sum + record.outputTokens, 0);
  const totalReasoning = usage.reduce((sum, record) => sum + record.reasoningTokens, 0);
  const totalCost = usage.reduce((sum, record) => sum + record.modelCostUsd, 0);
  const totalToolCalls = usage.reduce((sum, record) => sum + record.toolCalls, 0);
  const totalClientActions = usage.reduce((sum, record) => sum + record.clientActions, 0);

  return (
    <div className='grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3'>
      <KpiCard label='模型成本合计' value={formatUsd(totalCost)} icon='usage' hint={`近 ${usage.length} 天`} />
      <KpiCard
        label='Tokens 合计'
        value={formatNumber(totalInput + totalOutput + totalReasoning)}
        icon='task'
        hint={`输入 ${formatNumber(totalInput)} / 输出 ${formatNumber(totalOutput)} / 推理 ${formatNumber(totalReasoning)}`}
      />
      <KpiCard
        label='Tool 调用'
        value={formatNumber(totalToolCalls)}
        icon='worker'
        hint={`Client Actions ${formatNumber(totalClientActions)}`}
      />
    </div>
  );
}

/** Audit 面板：该 Host 的审计记录。 */
export function HostAuditTab({ entries }: { entries: AuditEntry[] }) {
  return (
    <Card className='py-0'>
      <CardHeader className='border-b px-4 py-3'>
        <CardTitle className='text-sm'>审计记录（{entries.length}）</CardTitle>
      </CardHeader>
      <CardContent className='p-0'>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>时间</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Resource</TableHead>
              <TableHead>结果</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className='text-muted-foreground h-20 text-center'>
                  暂无审计记录
                </TableCell>
              </TableRow>
            ) : (
              entries.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className='text-muted-foreground text-xs'>
                    {formatDateTime(entry.timestamp)}
                  </TableCell>
                  <TableCell className='text-xs'>{entry.actor}</TableCell>
                  <TableCell className='font-mono text-xs'>{entry.action}</TableCell>
                  <TableCell className='font-mono text-xs'>
                    {entry.resourceType}/{entry.resourceId}
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={lifecycleTone(entry.result)} withDot={false}>
                      {entry.result === 'succeeded' ? '成功' : entry.result === 'failed' ? '失败' : '拒绝'}
                    </StatusBadge>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
