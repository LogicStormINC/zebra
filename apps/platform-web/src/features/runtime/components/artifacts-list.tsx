'use client';
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId } from '@/components/platform/mono-id';
import { formatBytes, formatDateTime } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import type { Artifact } from '@/lib/platform/types';

const KIND_LABELS: Record<Artifact['kind'], string> = {
  patch: 'Patch',
  report: '报告',
  screenshot: '截图',
  log: '日志',
  export: '导出',
  diagnostic_bundle: '诊断包'
};

/** Artifacts 全局列表：kind 筛选 + 下载（演示 toast）。 */
export function ArtifactsList({ artifacts }: { artifacts: Artifact[] }) {
  const [kindFilter, setKindFilter] = useState<string>('all');

  const kinds = useMemo(() => [...new Set(artifacts.map((artifact) => artifact.kind))], [artifacts]);
  const filtered = useMemo(
    () => (kindFilter === 'all' ? artifacts : artifacts.filter((artifact) => artifact.kind === kindFilter)),
    [artifacts, kindFilter]
  );

  if (artifacts.length === 0) {
    return (
      <EmptyState
        icon='artifact'
        title='暂无产物'
        description='报告、补丁、导出等产物按 digest 存档，可随时下载校验'
      />
    );
  }

  const selectItems: Record<string, string> = {
    all: '全部 Kind',
    ...Object.fromEntries(kinds.map((kind) => [kind, KIND_LABELS[kind] ?? kind]))
  };

  return (
    <div className='flex flex-col gap-3'>
      <div className='flex items-center gap-2'>
        <Select items={selectItems} value={kindFilter} onValueChange={(value) => setKindFilter(String(value ?? 'all'))}>
          <SelectTrigger className='w-44'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部 Kind</SelectItem>
              {kinds.map((kind) => (
                <SelectItem key={kind} value={kind}>
                  {KIND_LABELS[kind] ?? kind}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <span className='text-muted-foreground text-xs'>
          {filtered.length} / {artifacts.length} 个产物
        </span>
      </div>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Task</TableHead>
              <TableHead>Bytes</TableHead>
              <TableHead>Digest</TableHead>
              <TableHead>Created At</TableHead>
              <TableHead className='text-right'>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((artifact) => (
              <TableRow key={artifact.id}>
                <TableCell className='font-medium'>{artifact.name}</TableCell>
                <TableCell>
                  <Badge variant='outline'>{KIND_LABELS[artifact.kind] ?? artifact.kind}</Badge>
                </TableCell>
                <TableCell>
                  <Link href={`/runtime/tasks/${artifact.taskId}`} className='text-primary hover:underline'>
                    <MonoId value={artifact.taskId} copyable={false} />
                  </Link>
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
                      toast.success('开始下载（演示）', {
                        description: `${artifact.name} · ${formatBytes(artifact.bytes)}`
                      })
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
    </div>
  );
}
