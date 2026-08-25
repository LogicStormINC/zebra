'use client';
import { useState } from 'react';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataList } from '@/components/platform/data-list';
import { EmptyState } from '@/components/platform/empty-state';
import { TASK_STATUS_LABELS } from '@/lib/platform/status';
import { formatNumber } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { OrchestrationNode, OrchestrationRun, TaskStatus } from '@/lib/platform/types';

/**
 * 编排 DAG 可视化（PRD 18.7）：纯 SVG/CSS 实现，按 dependsOn 做最长路径分层。
 * 不引入 react-flow；状态用「颜色 + 文字」双通道表达。
 */

const NODE_WIDTH = 208;
const NODE_HEIGHT = 96;
const GAP_X = 56;
const GAP_Y = 24;

type StatusStyle = { stroke: string; border: string; badge: string };

const STATUS_STYLES: Record<string, StatusStyle> = {
  blocked: { stroke: '#9ca3af', border: 'border-gray-400/50', badge: 'text-gray-600 dark:text-gray-400' },
  queued: { stroke: '#9ca3af', border: 'border-gray-400/40 border-dashed', badge: 'text-gray-600 dark:text-gray-400' },
  running: { stroke: '#0ea5e9', border: 'border-sky-500/60', badge: 'text-sky-700 dark:text-sky-400' },
  waiting: { stroke: '#8b5cf6', border: 'border-violet-500/60', badge: 'text-violet-700 dark:text-violet-400' },
  failed: { stroke: '#ef4444', border: 'border-red-500/60', badge: 'text-red-700 dark:text-red-400' },
  uncertain: { stroke: '#f97316', border: 'border-orange-500/60', badge: 'text-orange-700 dark:text-orange-400' },
  completed: { stroke: '#10b981', border: 'border-emerald-500/60', badge: 'text-emerald-700 dark:text-emerald-400' }
};

function statusStyle(status: TaskStatus): StatusStyle {
  if (status.startsWith('waiting_') || status === 'suspended') return STATUS_STYLES.waiting!;
  return STATUS_STYLES[status] ?? STATUS_STYLES.blocked!;
}

/** 最长路径分层：无依赖节点在第 0 层，其余为 1 + max(依赖层)。 */
function computeLayers(nodes: OrchestrationNode[]): string[][] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const layerOf = new Map<string, number>();
  const depth = (id: string): number => {
    const cached = layerOf.get(id);
    if (cached !== undefined) return cached;
    layerOf.set(id, 0); // 防御环依赖
    const node = byId.get(id);
    const value =
      !node || node.dependsOn.length === 0
        ? 0
        : 1 +
          Math.max(
            ...node.dependsOn.map((dep) => (byId.has(dep) ? depth(dep) : 0))
          );
    layerOf.set(id, value);
    return value;
  };
  nodes.forEach((node) => depth(node.id));
  const layers: string[][] = [];
  for (const node of nodes) {
    const layer = layerOf.get(node.id) ?? 0;
    layers[layer] = [...(layers[layer] ?? []), node.id];
  }
  return layers.filter(Boolean);
}

export function OrchestrationDag({ run }: { run: OrchestrationRun }) {
  const nodes = run.nodes;
  const [selectedId, setSelectedId] = useState<string | null>(nodes[0]?.id ?? null);

  if (nodes.length === 0) {
    return <EmptyState icon='orchestration' title='该编排运行没有节点' description='Orchestrator 尚未生成任何计划节点' />;
  }

  const layers = computeLayers(nodes);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const positions = new Map<string, { x: number; y: number }>();
  layers.forEach((layer, layerIndex) => {
    layer.forEach((id, indexInLayer) => {
      positions.set(id, {
        x: layerIndex * (NODE_WIDTH + GAP_X),
        y: indexInLayer * (NODE_HEIGHT + GAP_Y)
      });
    });
  });

  const width = layers.length * (NODE_WIDTH + GAP_X);
  const height = Math.max(...layers.map((layer) => layer.length)) * (NODE_HEIGHT + GAP_Y);
  const markerId = `dag-arrow-${run.runRef}`;
  const selected = selectedId ? byId.get(selectedId) : undefined;

  const edges = nodes.flatMap((node) =>
    node.dependsOn
      .filter((dep) => positions.has(dep))
      .map((dep) => {
        const from = positions.get(dep)!;
        const to = positions.get(node.id)!;
        return {
          id: `${dep}->${node.id}`,
          path: `M ${from.x + NODE_WIDTH} ${from.y + NODE_HEIGHT / 2} C ${from.x + NODE_WIDTH + GAP_X / 2} ${from.y + NODE_HEIGHT / 2}, ${to.x - GAP_X / 2} ${to.y + NODE_HEIGHT / 2}, ${to.x} ${to.y + NODE_HEIGHT / 2}`,
          stroke: statusStyle(byId.get(dep)!.status).stroke
        };
      })
  );

  return (
    <div className='flex flex-col gap-4'>
      <div className='scroll-area overflow-x-auto rounded-lg border p-4'>
        <div className='relative' style={{ width: Math.max(width - GAP_X, 320), height: Math.max(height - GAP_Y, 120) }}>
          <svg className='pointer-events-none absolute inset-0' width={Math.max(width - GAP_X, 320)} height={Math.max(height - GAP_Y, 120)}>
            <defs>
              <marker id={markerId} viewBox='0 0 8 8' refX='7' refY='4' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>
                <path d='M 0 0 L 8 4 L 0 8 z' fill='#94a3b8' />
              </marker>
            </defs>
            {edges.map((edge) => (
              <path
                key={edge.id}
                d={edge.path}
                fill='none'
                stroke={edge.stroke}
                strokeWidth={1.6}
                strokeOpacity={0.55}
                markerEnd={`url(#${markerId})`}
              />
            ))}
          </svg>
          {nodes.map((node) => {
            const position = positions.get(node.id)!;
            const style = statusStyle(node.status);
            const isSelected = node.id === selectedId;
            return (
              <div
                key={node.id}
                role='button'
                tabIndex={0}
                aria-pressed={isSelected}
                onClick={() => setSelectedId(node.id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    setSelectedId(node.id);
                  }
                }}
                className={cn(
                  'absolute flex cursor-pointer flex-col justify-between rounded-lg border bg-card p-2.5 text-left shadow-sm transition-shadow hover:shadow-md focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
                  style.border,
                  isSelected && 'ring-primary ring-2'
                )}
                style={{ left: position.x, top: position.y, width: NODE_WIDTH, height: NODE_HEIGHT }}
              >
                <div className='flex items-start justify-between gap-2'>
                  <span className='text-foreground truncate text-sm font-medium'>{node.label}</span>
                  {node.childTaskId && (
                    <Link
                      href={`/runtime/tasks/${node.childTaskId}`}
                      className='text-primary shrink-0'
                      aria-label={`打开子任务 ${node.childTaskId}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      <Icons.externalLink className='size-3.5' />
                    </Link>
                  )}
                </div>
                <div className='flex items-center justify-between gap-2'>
                  <Badge variant='outline' className='text-xs'>
                    {node.role}
                  </Badge>
                  <span className={cn('flex items-center gap-1 text-xs font-medium', style.badge)}>
                    <span className='size-1.5 rounded-full' style={{ backgroundColor: style.stroke }} />
                    {TASK_STATUS_LABELS[node.status] ?? node.status}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className='flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs'>
        {(['completed', 'running', 'waiting_approval', 'blocked', 'failed', 'uncertain'] as TaskStatus[]).map((status) => (
          <span key={status} className={cn('flex items-center gap-1.5', statusStyle(status).badge)}>
            <span className='size-2 rounded-full' style={{ backgroundColor: statusStyle(status).stroke }} />
            {TASK_STATUS_LABELS[status]}
          </span>
        ))}
        <span className='text-muted-foreground'>连线颜色 = 依赖节点的状态；等待类状态统一为紫色</span>
      </div>

      {selected ? <NodeDetailCard node={selected} labelOf={(id) => byId.get(id)?.label ?? id} /> : null}
    </div>
  );
}

function NodeDetailCard({ node, labelOf }: { node: OrchestrationNode; labelOf: (id: string) => string }) {
  return (
    <Card className='py-0'>
      <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
        <CardTitle className='flex items-center gap-2 text-sm'>
          <Icons.orchestration className='size-4' />
          {node.label}
          <span className='text-muted-foreground font-mono text-xs'>{node.id}</span>
        </CardTitle>
        <span className={cn('flex items-center gap-1.5 text-xs font-medium', statusStyle(node.status).badge)}>
          <span className='size-2 rounded-full' style={{ backgroundColor: statusStyle(node.status).stroke }} />
          {TASK_STATUS_LABELS[node.status] ?? node.status}
        </span>
      </CardHeader>
      <CardContent className='p-4'>
        <DataList
          columns={3}
          items={[
            { label: 'Role', value: node.role },
            {
              label: 'Depends On',
              value:
                node.dependsOn.length === 0 ? '无' : node.dependsOn.map((dep) => labelOf(dep)).join('、')
            },
            { label: 'Budget Tokens', value: formatNumber(node.budgetTokens) },
            { label: 'Evidence', value: node.evidence ?? '—' },
            {
              label: 'Completion Gate',
              value: node.gate ? <Badge variant='outline'>{node.gate}</Badge> : '无'
            },
            {
              label: 'Child Task',
              value: node.childTaskId ? (
                <Link href={`/runtime/tasks/${node.childTaskId}`} className='text-primary hover:underline'>
                  {node.childTaskId}
                </Link>
              ) : (
                '—'
              )
            }
          ]}
        />
      </CardContent>
    </Card>
  );
}
