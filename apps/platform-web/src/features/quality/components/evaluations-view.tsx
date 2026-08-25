'use client';

import { useState } from 'react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Progress, ProgressTrack } from '@/components/ui/progress';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { DataList } from '@/components/platform/data-list';
import { EmptyState } from '@/components/platform/empty-state';
import { KpiCard } from '@/components/platform/kpi-card';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime, formatDuration, formatUsd } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { AgentRelease, EvaluationRun } from '@/lib/platform/types';

const EVAL_STATUS_LABELS: Record<EvaluationRun['status'], string> = {
  passed: '通过',
  failed: '失败',
  running: '运行中',
  pending: '待运行'
};

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

/** Evaluation 列表 + 指标详情 Dialog。 */
export function EvaluationsView({
  evaluations,
  releases
}: {
  evaluations: EvaluationRun[];
  releases: AgentRelease[];
}) {
  const [selected, setSelected] = useState<EvaluationRun | null>(null);
  const releaseName = (id: string) => {
    const release = releases.find((item) => item.id === id);
    return release ? `${release.definitionName} v${release.version}` : id;
  };

  return (
    <div className='flex flex-col gap-4'>
      {evaluations.length === 0 ? (
        <EmptyState
          title='暂无 Evaluation'
          description='对 Agent Release 运行 Golden Dataset 评估后会展示在这里'
          icon='evaluation'
        />
      ) : (
        <div className='overflow-x-auto rounded-lg border'>
          <Table>
            <TableHeader className='bg-muted'>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Agent Release</TableHead>
                <TableHead>Dataset</TableHead>
                <TableHead className='w-40'>Quality Score</TableHead>
                <TableHead>Tool Accuracy</TableHead>
                <TableHead>Structured Output</TableHead>
                <TableHead>Latency P95</TableHead>
                <TableHead>Cost / Run</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {evaluations.map((evaluation) => (
                <TableRow
                  key={evaluation.id}
                  className='cursor-pointer'
                  onClick={() => setSelected(evaluation)}
                >
                  <TableCell className='font-mono text-xs'>{evaluation.id}</TableCell>
                  <TableCell className='max-w-56 truncate text-sm font-medium'>
                    {evaluation.name}
                  </TableCell>
                  <TableCell className='text-sm'>{releaseName(evaluation.agentReleaseId)}</TableCell>
                  <TableCell className='font-mono text-xs'>{evaluation.dataset}</TableCell>
                  <TableCell>
                    <div className='flex items-center gap-2'>
                      <Progress
                        value={evaluation.qualityScore * 100}
                        className='min-w-24 gap-2'
                        aria-label={`质量分 ${percent(evaluation.qualityScore)}`}
                      >
                        <ProgressTrack className='w-16'>
                          <span className='sr-only'>{percent(evaluation.qualityScore)}</span>
                        </ProgressTrack>
                      </Progress>
                      <span className='tabular-nums text-xs font-medium'>
                        {percent(evaluation.qualityScore)}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className='tabular-nums'>{percent(evaluation.toolAccuracy)}</TableCell>
                  <TableCell className='tabular-nums'>
                    {percent(evaluation.structuredOutputPassRate)}
                  </TableCell>
                  <TableCell className='tabular-nums'>
                    {formatDuration(evaluation.latencyP95Ms)}
                  </TableCell>
                  <TableCell className='tabular-nums'>
                    {formatUsd(evaluation.costUsdPerRun)}
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={lifecycleTone(evaluation.status)}>
                      {EVAL_STATUS_LABELS[evaluation.status]}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className='text-muted-foreground text-xs'>
                    {formatDateTime(evaluation.createdAt)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className='max-w-lg'>
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle>{selected.name}</DialogTitle>
                <DialogDescription className='font-mono text-xs'>
                  {selected.id} · {releaseName(selected.agentReleaseId)} · dataset{' '}
                  {selected.dataset}
                </DialogDescription>
              </DialogHeader>

              <div className='grid grid-cols-2 gap-3'>
                <KpiCard
                  label='Quality Score'
                  value={percent(selected.qualityScore)}
                  tone={selected.qualityScore >= 0.85 ? 'success' : selected.qualityScore >= 0.7 ? 'warning' : 'failure'}
                  icon='evaluation'
                />
                <KpiCard
                  label='Tool Accuracy'
                  value={percent(selected.toolAccuracy)}
                  tone={selected.toolAccuracy >= 0.9 ? 'success' : 'warning'}
                  icon='worker'
                />
                <KpiCard
                  label='Structured Output Pass Rate'
                  value={percent(selected.structuredOutputPassRate)}
                  tone={selected.structuredOutputPassRate >= 0.95 ? 'success' : 'warning'}
                  icon='code'
                />
                <KpiCard
                  label='Latency P95'
                  value={formatDuration(selected.latencyP95Ms)}
                  tone={selected.latencyP95Ms <= 10_000 ? 'success' : 'warning'}
                  icon='clock'
                />
              </div>

              <DataList
                columns={2}
                items={[
                  { label: 'Cost per Run', value: formatUsd(selected.costUsdPerRun) },
                  {
                    label: 'Status',
                    value: (
                      <StatusBadge tone={lifecycleTone(selected.status)}>
                        {EVAL_STATUS_LABELS[selected.status]}
                      </StatusBadge>
                    )
                  },
                  { label: 'Created', value: formatDateTime(selected.createdAt) },
                  { label: 'Dataset', value: <span className='font-mono text-xs'>{selected.dataset}</span> }
                ]}
              />

              <p className='text-muted-foreground text-xs'>
                指标说明：Quality Score 为 golden dataset 综合评分；Tool Accuracy
                衡量工具调用参数与时机正确率；Structured Output Pass Rate 衡量结构化输出 Schema
                通过率；Latency P95 与 Cost per Run 用于发布成本门禁。
              </p>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
