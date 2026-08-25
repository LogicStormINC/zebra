'use client';

import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';

import { Button } from '@/components/ui/button';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { DataTable } from '@/components/ui/table/data-table';
import { DataTableToolbar } from '@/components/ui/table/data-table-toolbar';
import { Icons } from '@/components/icons';
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { relativeTime } from '@/lib/platform/format';
import type { Host } from '@/lib/platform/types';
import {
  CONFORMANCE_LABELS,
  ENVIRONMENT_LABELS,
  HOST_STATUS_LABELS,
  TRUST_HEALTH_LABELS,
  hostStatusTone,
  labelOptions
} from '../lib/labels';
import { useMockDataTable } from '../lib/use-mock-data-table';

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
    cell: ({ row }) => <span className='text-sm'>{row.original.owner}</span>
  },
  {
    id: 'environment',
    accessorKey: 'environment',
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title='Environment' />,
    cell: ({ row }) => (
      <StatusBadge tone={row.original.environment === 'production' ? 'running' : 'draft'} withDot={false}>
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
      )
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
    cell: ({ row }) => (
      <Button
        variant='ghost'
        size='icon-sm'
        render={
          <Link
            href={`/integrations/hosts/${row.original.id}`}
            aria-label={`查看 ${row.original.name} 详情`}
          />
        }
      >
        <Icons.chevronRight className='size-4' />
      </Button>
    )
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
    lastConformance: (row: Host) => row.lastConformance
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
