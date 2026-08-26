'use client';
import Link from 'next/link';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { relativeTime } from '@/lib/platform/format';
import type { AgentDefinition } from '@/lib/platform/types';

/** Agent Definition 列表行（PRD 14.1）：补充 id → name 的展示字段。 */
export type DefinitionRow = AgentDefinition & {
  modelPolicyName: string;
  toolProfileName: string;
  runtimeProfileName: string;
  publishedReleaseVersion?: number;
  publishedReleaseChannel?: 'stable' | 'canary' | 'dry-run';
};

const LIFECYCLE_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

const CHANNEL_LABELS: Record<string, string> = {
  stable: 'Stable',
  canary: 'Canary',
  'dry-run': 'Dry Run'
};

export function DefinitionsTable({ rows }: { rows: DefinitionRow[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        icon='agent'
        title='暂无 Agent Definition'
        description='创建第一个 Definition 后，即可进入 Draft → Validate → Release 流程'
      />
    );
  }

  return (
    <div className='flex flex-col gap-3'>
      <div className='flex items-center justify-end gap-2'>
        <Button
          size='sm'
          onClick={() =>
            toast.info('创建 Definition（演示）', {
              description: '真实环境将打开 Definition 创建向导，填充 8 个 Ref 字段'
            })
          }
        >
          创建 Definition
        </Button>
      </div>
      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Definition ID</TableHead>
              <TableHead>Latest Draft</TableHead>
              <TableHead>Latest Version</TableHead>
              <TableHead>Published Release</TableHead>
              <TableHead>Capability Ceiling</TableHead>
              <TableHead>Model Policy</TableHead>
              <TableHead>Tool Profile</TableHead>
              <TableHead>Runtime Profile</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell className='font-medium'>
                  <Link
                    href={`/agents/definitions/${row.id}`}
                    className='text-primary hover:underline'
                  >
                    {row.name}
                  </Link>
                </TableCell>
                <TableCell>
                  <MonoId value={row.id} copyable={false} />
                </TableCell>
                <TableCell className='tabular-nums'>rev {row.latestDraftRevision}</TableCell>
                <TableCell className='tabular-nums'>v{row.latestVersion}</TableCell>
                <TableCell>
                  {row.publishedReleaseId ? (
                    <span className='inline-flex items-center gap-1.5'>
                      <Link
                        href={`/agents/definitions/${row.id}`}
                        className='text-primary text-sm hover:underline'
                      >
                        v{row.publishedReleaseVersion}
                      </Link>
                      {row.publishedReleaseChannel && (
                        <Badge variant='outline' className='text-xs'>
                          {CHANNEL_LABELS[row.publishedReleaseChannel] ?? row.publishedReleaseChannel}
                        </Badge>
                      )}
                      <Link
                        href='/agents/releases'
                        className='text-muted-foreground text-xs hover:underline'
                      >
                        releases
                      </Link>
                    </span>
                  ) : (
                    <span className='text-muted-foreground text-sm'>未发布</span>
                  )}
                </TableCell>
                <TableCell>
                  <span className='flex max-w-[220px] flex-wrap gap-1'>
                    {row.capabilityCeiling.map((capability) => (
                      <Badge key={capability} variant='secondary' className='font-mono text-xs'>
                        {capability}
                      </Badge>
                    ))}
                  </span>
                </TableCell>
                <TableCell className='text-sm'>{row.modelPolicyName}</TableCell>
                <TableCell className='text-sm'>{row.toolProfileName}</TableCell>
                <TableCell className='text-sm'>{row.runtimeProfileName}</TableCell>
                <TableCell>
                  <StatusBadge tone={lifecycleTone(row.status)}>
                    {LIFECYCLE_LABELS[row.status] ?? row.status}
                  </StatusBadge>
                </TableCell>
                <TableCell className='text-muted-foreground text-sm'>
                  {relativeTime(row.updatedAt)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
