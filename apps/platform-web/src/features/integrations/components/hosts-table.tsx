'use client';

import Link from 'next/link';
import { useState } from 'react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { DataTable } from '@/components/ui/table/data-table';
import { DataTableToolbar } from '@/components/ui/table/data-table-toolbar';
import { Icons } from '@/components/icons';
import { MonoId } from '@/components/platform/mono-id';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { relativeTime } from '@/lib/platform/format';
import { repository } from '@/lib/platform/repository';
import type { Host } from '@/lib/platform/types';
import {
  CONFORMANCE_LABELS,
  CONNECTOR_HEALTH_LABELS,
  ENVIRONMENT_LABELS,
  HOST_STATUS_LABELS,
  TRUST_HEALTH_LABELS,
  hostStatusTone,
  labelOptions
} from '../lib/labels';
import { useMockDataTable } from '../lib/use-mock-data-table';

/** Connector 健康状态查找表（静态 mock，模块级构建一次）。 */
const CONNECTOR_HEALTH_BY_ID = new Map(
  repository.connectors().map((connector) => [connector.id, connector.health])
);

const connectorHealthOf = (host: Host) =>
  (host.connectorId ? CONNECTOR_HEALTH_BY_ID.get(host.connectorId) : undefined) ?? '';

/** Owner 去重筛选项（PRD 10.1：筛选按 Owner 团队）。 */
const OWNER_OPTIONS = [...new Set(repository.hosts().map((host) => host.owner))]
  .toSorted()
  .map((owner) => ({ value: owner, label: owner }));

const FRONTEND_PROFILE_OPTIONS = [
  { value: 'yes', label: '有 Frontend Profile' },
  { value: 'no', label: '无 Frontend Profile' }
];

/** Host 行操作（PRD 10.1）：详情 / 继续接入 / Conformance / 暂停 / 审计。 */
function HostRowActions({ host }: { host: Host }) {
  const [suspendOpen, setSuspendOpen] = useState(false);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button variant='ghost' size='icon-sm' aria-label={`打开 ${host.name} 的操作菜单`} />
          }
        >
          <Icons.moreHorizontal className='size-4' />
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end' sideOffset={4} className='w-44'>
          <DropdownMenuItem
            render={
              <Link href={`/integrations/hosts/${host.id}`} aria-label={`查看 ${host.name} 详情`} />
            }
          >
            <Icons.chevronRight className='size-4' />
            查看详情
          </DropdownMenuItem>
          {host.onboardingStep < 7 && (
            <DropdownMenuItem
              render={<Link href='/integrations/onboarding' aria-label={`继续接入 ${host.name}`} />}
            >
              <Icons.forms className='size-4' />
              继续接入（{host.onboardingStep}/7）
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            onClick={() =>
              toast.info('Conformance Run 已触发（演示）', {
                description: `将对 ${host.name} 的 Connector 与 Manifest 执行一致性检查`
              })
            }
          >
            <Icons.conformance className='size-4' />
            运行 Conformance
          </DropdownMenuItem>
          {host.status === 'active' && (
            <DropdownMenuItem variant='destructive' onClick={() => setSuspendOpen(true)}>
              <Icons.warning className='size-4' />
              暂停接入
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            render={<Link href='/governance/audit' aria-label={`查看 ${host.name} 相关审计`} />}
          >
            <Icons.audit className='size-4' />
            查看审计
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <RiskConfirmDialog
        open={suspendOpen}
        onOpenChange={setSuspendOpen}
        title={`暂停 ${host.name} 接入`}
        impact='暂停后该 Host 的新 Task 将被拒绝，已运行 Task 继续完成；入站信任保持不变。'
        irreversibility='可通过同样的高风险操作恢复接入。'
        currentRevision={`status ${host.status}`}
        actionLabel='确认暂停'
        onConfirm={() => {
          toast.warning('暂停请求已提交（演示）', { description: `${host.name} · ${host.appId}` });
        }}
      />
    </>
  );
}

const columns: ColumnDef<Host, unknown>[] = [
  {
    id: 'name',
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Host 名称' />,
    cell: ({ row }) => (
      <div className='flex flex-col gap-0.5'>
        <Link
          href={`/integrations/hosts/${row.original.id}`}
          className='text-primary font-medium hover:underline'
        >
          {row.original.name}
        </Link>
        <span className='text-muted-foreground text-xs'>
          {row.original.onboardingStep === 7 ? '接入完成' : `向导 ${row.original.onboardingStep}/7`}
        </span>
      </div>
    ),
    enableColumnFilter: true,
    meta: { label: 'Host 名称', placeholder: '搜索 Host 名称…', variant: 'text' }
  },
  {
    id: 'appId',
    accessorKey: 'appId',
    header: 'Host App ID',
    cell: ({ row }) => <MonoId value={row.original.appId} head={12} tail={4} copyable={false} />
  },
  {
    id: 'owner',
    accessorKey: 'owner',
    header: 'Owner',
    cell: ({ row }) => <span className='text-sm'>{row.original.owner}</span>,
    enableColumnFilter: true,
    meta: {
      label: 'Owner',
      variant: 'multiSelect',
      options: OWNER_OPTIONS
    }
  },
  {
    id: 'environment',
    accessorKey: 'environment',
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title='Environment' />,
    cell: ({ row }) => (
      <StatusBadge
        tone={row.original.environment === 'production' ? 'running' : 'draft'}
        withDot={false}
      >
        {ENVIRONMENT_LABELS[row.original.environment]}
      </StatusBadge>
    ),
    enableColumnFilter: true,
    meta: {
      label: 'Environment',
      variant: 'multiSelect',
      options: labelOptions(ENVIRONMENT_LABELS)
    }
  },
  {
    id: 'inboundTrustHealth',
    accessorKey: 'inboundTrustHealth',
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title='Inbound Trust' />,
    cell: ({ row }) => (
      <StatusBadge tone={lifecycleTone(row.original.inboundTrustHealth)}>
        {TRUST_HEALTH_LABELS[row.original.inboundTrustHealth]}
      </StatusBadge>
    ),
    enableColumnFilter: true,
    meta: {
      label: 'Trust Health',
      variant: 'multiSelect',
      options: labelOptions(TRUST_HEALTH_LABELS)
    }
  },
  {
    id: 'connectorRevision',
    accessorKey: 'connectorRevision',
    header: 'Connector 版本',
    cell: ({ row }) =>
      row.original.connectorRevision ? (
        <span className='font-mono text-xs'>conn rev {row.original.connectorRevision}</span>
      ) : (
        <span className='text-muted-foreground'>—</span>
      )
  },
  {
    id: 'connectorStatus',
    accessorFn: (row) => connectorHealthOf(row),
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title='Connector 状态' />,
    cell: ({ row }) => {
      const health = connectorHealthOf(row.original);
      return health ? (
        <StatusBadge tone={lifecycleTone(health)} withDot={false}>
          {CONNECTOR_HEALTH_LABELS[health]}
        </StatusBadge>
      ) : (
        <span className='text-muted-foreground'>—</span>
      );
    },
    enableColumnFilter: true,
    meta: {
      label: 'Connector 状态',
      variant: 'multiSelect',
      options: labelOptions(CONNECTOR_HEALTH_LABELS)
    }
  },
  {
    id: 'manifestRevision',
    accessorKey: 'manifestRevision',
    header: 'Manifest 版本',
    cell: ({ row }) =>
      row.original.manifestRevision ? (
        <span className='font-mono text-xs'>rev {row.original.manifestRevision}</span>
      ) : (
        <span className='text-muted-foreground'>—</span>
      )
  },
  {
    id: 'frontendProfileRevision',
    accessorKey: 'frontendProfileRevision',
    header: 'Frontend Profile',
    cell: ({ row }) =>
      row.original.frontendProfileRevision ? (
        <span className='font-mono text-xs'>rev {row.original.frontendProfileRevision}</span>
      ) : (
        <span className='text-muted-foreground'>—</span>
      ),
    enableColumnFilter: true,
    meta: {
      label: 'Frontend Profile',
      variant: 'multiSelect',
      options: FRONTEND_PROFILE_OPTIONS
    }
  },
  {
    id: 'agentReleaseCount',
    accessorKey: 'agentReleaseCount',
    header: 'Agent Releases',
    cell: ({ row }) => <span className='tabular-nums'>{row.original.agentReleaseCount}</span>
  },
  {
    id: 'lastConformance',
    accessorKey: 'lastConformance',
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title='Conformance' />,
    cell: ({ row }) => (
      <StatusBadge tone={lifecycleTone(row.original.lastConformance)} withDot={false}>
        {CONFORMANCE_LABELS[row.original.lastConformance]}
      </StatusBadge>
    ),
    enableColumnFilter: true,
    meta: {
      label: 'Conformance',
      variant: 'multiSelect',
      options: labelOptions(CONFORMANCE_LABELS)
    }
  },
  {
    id: 'status',
    accessorKey: 'status',
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title='Status' />,
    cell: ({ row }) => (
      <StatusBadge tone={hostStatusTone(row.original.status)}>
        {HOST_STATUS_LABELS[row.original.status]}
      </StatusBadge>
    ),
    enableColumnFilter: true,
    meta: {
      label: 'Status',
      variant: 'multiSelect',
      options: labelOptions(HOST_STATUS_LABELS)
    }
  },
  {
    id: 'updatedAt',
    accessorKey: 'updatedAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Updated At' />,
    cell: ({ row }) => (
      <span className='text-muted-foreground text-xs'>{relativeTime(row.original.updatedAt)}</span>
    )
  },
  {
    id: 'actions',
    enableSorting: false,
    header: () => <span className='sr-only'>操作</span>,
    cell: ({ row }) => <HostRowActions host={row.original} />
  }
];

const SPEC = {
  textFilters: {
    name: (row: Host) => row.name
  } satisfies Record<string, (row: Host) => string>,
  selectFilters: {
    status: (row: Host) => row.status,
    environment: (row: Host) => row.environment,
    inboundTrustHealth: (row: Host) => row.inboundTrustHealth,
    lastConformance: (row: Host) => row.lastConformance,
    owner: (row: Host) => row.owner,
    connectorStatus: (row: Host) => connectorHealthOf(row),
    frontendProfileRevision: (row: Host) => (row.frontendProfileId ? 'yes' : 'no')
  } satisfies Record<string, (row: Host) => string>,
  sortAccessors: {
    name: (row: Host) => row.name,
    agentReleaseCount: (row: Host) => row.agentReleaseCount,
    connectorRevision: (row: Host) => row.connectorRevision ?? 0,
    manifestRevision: (row: Host) => row.manifestRevision ?? 0,
    frontendProfileRevision: (row: Host) => row.frontendProfileRevision ?? 0,
    updatedAt: (row: Host) => row.updatedAt
  } satisfies Record<string, (row: Host) => string | number>
};

/** Host 应用列表（PRD 10.1）。 */
export function HostsTable({ hosts }: { hosts: Host[] }) {
  const { table, total } = useMockDataTable({ rows: hosts, columns, spec: SPEC });

  return (
    <div className='flex flex-1 flex-col gap-4'>
      <p className='text-muted-foreground px-1 text-sm'>共 {total} 个 Host 应用</p>
      <DataTable table={table}>
        <DataTableToolbar table={table} />
      </DataTable>
    </div>
  );
}
