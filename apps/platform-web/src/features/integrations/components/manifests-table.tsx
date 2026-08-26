'use client';

import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';

import { Button } from '@/components/ui/button';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { DataTable } from '@/components/ui/table/data-table';
import { DataTableToolbar } from '@/components/ui/table/data-table-toolbar';
import { Icons } from '@/components/icons';
import { DigestTag } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import type { BackendManifest } from '@/lib/platform/types';
import { CONFORMANCE_LABELS, REVISION_STATUS_LABELS, labelOptions } from '../lib/labels';
import { useMockDataTable } from '../lib/use-mock-data-table';

const columns: ColumnDef<BackendManifest, unknown>[] = [
  {
    id: 'hostAppId',
    accessorKey: 'hostAppId',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Host App ID' />,
    cell: ({ row }) => (
      <span className='font-mono text-xs font-medium'>{row.original.hostAppId}</span>
    ),
    enableColumnFilter: true,
    meta: { label: 'Host App ID', placeholder: '搜索 Host…', variant: 'text' }
  },
  {
    id: 'id',
    accessorKey: 'id',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Manifest ID' />,
    cell: ({ row }) => (
      <Link
        href={`/integrations/backend-manifests/${row.original.id}`}
        className='text-primary font-mono text-xs font-medium hover:underline'
      >
        {row.original.id}
      </Link>
    )
  },
  {
    id: 'revision',
    accessorKey: 'revision',
    header: 'Revision',
    cell: ({ row }) => <span className='font-mono text-xs'>rev {row.original.revision}</span>
  },
  {
    id: 'protocolVersion',
    accessorKey: 'protocolVersion',
    enableSorting: false,
    header: 'Protocol',
    cell: ({ row }) => (
      <span className='text-muted-foreground font-mono text-xs'>{row.original.protocolVersion}</span>
    )
  },
  {
    id: 'toolCount',
    accessorFn: (row) => row.tools.length,
    header: 'Tools',
    cell: ({ row }) => <span className='tabular-nums'>{row.original.tools.length}</span>
  },
  {
    id: 'readTools',
    accessorKey: 'readTools',
    header: 'Read',
    cell: ({ row }) => <span className='tabular-nums'>{row.original.readTools}</span>
  },
  {
    id: 'writeTools',
    accessorKey: 'writeTools',
    header: 'Write',
    cell: ({ row }) => <span className='tabular-nums'>{row.original.writeTools}</span>
  },
  {
    id: 'reconcileTools',
    accessorKey: 'reconcileTools',
    header: 'Reconcile',
    cell: ({ row }) => <span className='tabular-nums'>{row.original.reconcileTools}</span>
  },
  {
    id: 'digest',
    accessorKey: 'digest',
    enableSorting: false,
    header: 'Digest',
    cell: ({ row }) => <DigestTag value={row.original.digest} />
  },
  {
    id: 'status',
    accessorKey: 'status',
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title='Status' />,
    cell: ({ row }) => (
      <StatusBadge tone={lifecycleTone(row.original.status)} withDot={false}>
        {REVISION_STATUS_LABELS[row.original.status]}
      </StatusBadge>
    ),
    enableColumnFilter: true,
    meta: {
      label: 'Status',
      variant: 'multiSelect',
      options: labelOptions(REVISION_STATUS_LABELS)
    }
  },
  {
    id: 'conformance',
    accessorKey: 'conformance',
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title='Conformance' />,
    cell: ({ row }) => (
      <StatusBadge tone={lifecycleTone(row.original.conformance)} withDot={false}>
        {CONFORMANCE_LABELS[row.original.conformance]}
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
    id: 'actions',
    enableSorting: false,
    header: () => <span className='sr-only'>操作</span>,
    cell: ({ row }) => (
      <Button
        variant='ghost'
        size='icon-sm'
        render={
          <Link
            href={`/integrations/backend-manifests/${row.original.id}`}
            aria-label={`打开 ${row.original.id} 编辑器`}
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
    hostAppId: (row: BackendManifest) => row.hostAppId
  } satisfies Record<string, (row: BackendManifest) => string>,
  selectFilters: {
    status: (row: BackendManifest) => row.status,
    conformance: (row: BackendManifest) => row.conformance
  } satisfies Record<string, (row: BackendManifest) => string>,
  sortAccessors: {
    hostAppId: (row: BackendManifest) => row.hostAppId,
    id: (row: BackendManifest) => row.id,
    revision: (row: BackendManifest) => row.revision,
    readTools: (row: BackendManifest) => row.readTools,
    writeTools: (row: BackendManifest) => row.writeTools,
    reconcileTools: (row: BackendManifest) => row.reconcileTools
  } satisfies Record<string, (row: BackendManifest) => string | number>
};

/** Backend Manifest 列表（PRD 12.1）。 */
export function ManifestsTable({ manifests }: { manifests: BackendManifest[] }) {
  const { table, total } = useMockDataTable({ rows: manifests, columns, spec: SPEC });

  return (
    <div className='flex flex-1 flex-col gap-4'>
      <p className='text-muted-foreground px-1 text-sm'>共 {total} 个 Backend Manifest</p>
      <DataTable table={table}>
        <DataTableToolbar table={table} />
      </DataTable>
    </div>
  );
}
