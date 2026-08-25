'use client';

import { useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { DataTable } from '@/components/ui/table/data-table';
import { DataTableToolbar } from '@/components/ui/table/data-table-toolbar';
import { Icons } from '@/components/icons';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { relativeTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { Environment, NamespaceBinding } from '@/lib/platform/types';
import {
  BINDING_STATUS_LABELS,
  ENVIRONMENT_LABELS,
  labelOptions
} from '../lib/labels';
import { useMockDataTable } from '../lib/use-mock-data-table';

type BindingForm = {
  hostAppId: string;
  namespace: string;
  environment: Environment;
  connectorRevision: string;
  manifestRevision: string;
  agentReleaseId: string;
  expectedRevision: string;
};

const EMPTY_FORM: BindingForm = {
  hostAppId: '',
  namespace: '',
  environment: 'staging',
  connectorRevision: '1',
  manifestRevision: '1',
  agentReleaseId: '',
  expectedRevision: ''
};

function CreateBindingDialog({
  open,
  onOpenChange,
  hosts,
  agentReleases
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  hosts: { appId: string; name: string }[];
  agentReleases: { id: string; label: string }[];
}) {
  const [form, setForm] = useState<BindingForm>(EMPTY_FORM);

  const submit = () => {
    if (
      form.hostAppId.length === 0 ||
      form.namespace.trim().length === 0 ||
      form.agentReleaseId.length === 0 ||
      form.expectedRevision.trim().length === 0
    ) {
      toast.error('请完整填写必填项', { description: 'Host / Namespace / Agent Release / Expected Revision' });
      return;
    }
    onOpenChange(false);
    setForm(EMPTY_FORM);
    toast.success('Binding 创建请求已提交（演示）', {
      description: `${form.hostAppId} · ${form.namespace} · expected revision ${form.expectedRevision}`
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle>新建 Namespace Binding</DialogTitle>
          <DialogDescription>
            将 Host 的 Connector / Manifest / Agent Release 组合绑定到一个 Namespace；
            expected revision 必填（Compare-And-Swap 防并发误升级，PRD 15）。
          </DialogDescription>
        </DialogHeader>

        <div className='grid grid-cols-2 gap-3'>
          <div className='space-y-1.5'>
            <Label>
              Host App ID<span className='text-destructive'>*</span>
            </Label>
            <Select
              value={form.hostAppId}
              onValueChange={(next) => setForm((prev) => ({ ...prev, hostAppId: next ?? '' }))}
            >
              <SelectTrigger className='w-full'>
                <SelectValue placeholder='选择 Host' />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {hosts.map((host) => (
                    <SelectItem key={host.appId} value={host.appId}>
                      {host.name}（{host.appId}）
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1.5'>
            <Label>
              Namespace<span className='text-destructive'>*</span>
            </Label>
            <Input
              className='font-mono'
              placeholder='host/env'
              value={form.namespace}
              onChange={(event) => setForm((prev) => ({ ...prev, namespace: event.target.value }))}
            />
          </div>
          <div className='space-y-1.5'>
            <Label>Environment</Label>
            <Select
              value={form.environment}
              onValueChange={(next) =>
                setForm((prev) => ({ ...prev, environment: (next ?? 'staging') as Environment }))
              }
            >
              <SelectTrigger className='w-full'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {(['development', 'staging', 'production'] as const).map((env) => (
                    <SelectItem key={env} value={env}>
                      {ENVIRONMENT_LABELS[env]}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1.5'>
            <Label>
              Agent Release<span className='text-destructive'>*</span>
            </Label>
            <Select
              value={form.agentReleaseId}
              onValueChange={(next) => setForm((prev) => ({ ...prev, agentReleaseId: next ?? '' }))}
            >
              <SelectTrigger className='w-full'>
                <SelectValue placeholder='选择 Agent Release' />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {agentReleases.map((release) => (
                    <SelectItem key={release.id} value={release.id}>
                      {release.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1.5'>
            <Label>Connector Rev</Label>
            <Input
              type='number'
              min={1}
              value={form.connectorRevision}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, connectorRevision: event.target.value }))
              }
            />
          </div>
          <div className='space-y-1.5'>
            <Label>Manifest Rev</Label>
            <Input
              type='number'
              min={1}
              value={form.manifestRevision}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, manifestRevision: event.target.value }))
              }
            />
          </div>
          <div className='space-y-1.5'>
            <Label>
              Expected Revision<span className='text-destructive'>*</span>
            </Label>
            <Input
              type='number'
              min={1}
              className='font-mono'
              placeholder='写入时进行 CAS 校验'
              value={form.expectedRevision}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, expectedRevision: event.target.value }))
              }
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={submit}>创建 Binding</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Namespace Binding 列表（PRD 15 / 24.4）。 */
export function BindingsTable({
  bindings,
  hosts,
  agentReleases,
  runningTasksByHost
}: {
  bindings: NamespaceBinding[];
  hosts: { appId: string; name: string }[];
  agentReleases: { id: string; label: string }[];
  runningTasksByHost: Record<string, number>;
}) {
  const [createOpen, setCreateOpen] = useState(false);

  const columns: ColumnDef<NamespaceBinding, unknown>[] = [
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
      id: 'namespace',
      accessorKey: 'namespace',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Namespace' />,
      cell: ({ row }) => <span className='font-mono text-xs'>{row.original.namespace}</span>,
      enableColumnFilter: true,
      meta: { label: 'Namespace', placeholder: '搜索 namespace…', variant: 'text' }
    },
    {
      id: 'environment',
      accessorKey: 'environment',
      enableSorting: false,
      header: ({ column }) => <DataTableColumnHeader column={column} title='Environment' />,
      cell: ({ row }) => ENVIRONMENT_LABELS[row.original.environment],
      enableColumnFilter: true,
      meta: { label: 'Environment', variant: 'multiSelect', options: labelOptions(ENVIRONMENT_LABELS) }
    },
    {
      id: 'connectorRevision',
      accessorKey: 'connectorRevision',
      header: 'Connector Rev',
      cell: ({ row }) => <span className='font-mono text-xs'>rev {row.original.connectorRevision}</span>
    },
    {
      id: 'manifestRevision',
      accessorKey: 'manifestRevision',
      header: 'Manifest Rev',
      cell: ({ row }) => <span className='font-mono text-xs'>rev {row.original.manifestRevision}</span>
    },
    {
      id: 'agentReleaseId',
      accessorKey: 'agentReleaseId',
      enableSorting: false,
      header: 'Agent Release',
      cell: ({ row }) => (
        <span className='font-mono text-xs'>{row.original.agentReleaseId}</span>
      )
    },
    {
      id: 'expectedRevision',
      accessorKey: 'expectedRevision',
      header: 'Expected Rev',
      cell: ({ row }) => <span className='font-mono text-xs tabular-nums'>{row.original.expectedRevision}</span>
    },
    {
      id: 'status',
      accessorKey: 'status',
      enableSorting: false,
      header: ({ column }) => <DataTableColumnHeader column={column} title='Status' />,
      cell: ({ row }) => (
        <StatusBadge
          tone={lifecycleTone(
            row.original.status === 'active'
              ? 'active'
              : row.original.status === 'canary'
                ? 'running'
                : 'pending'
          )}
        >
          {BINDING_STATUS_LABELS[row.original.status]}
        </StatusBadge>
      ),
      enableColumnFilter: true,
      meta: {
        label: 'Status',
        variant: 'multiSelect',
        options: labelOptions(BINDING_STATUS_LABELS)
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
      cell: ({ row }) => {
        const binding = row.original;
        const targetRevision = Math.max(1, binding.connectorRevision - 1);
        return (
          <RiskConfirmDialog
            trigger={
              <Button variant='outline' size='sm'>
                回滚
              </Button>
            }
            title={`回滚 Binding ${binding.namespace}`}
            impact={`目标版本：connector rev ${targetRevision} / manifest rev ${Math.max(1, binding.manifestRevision - 1)}；影响 namespace：${binding.namespace}；运行中 Task：${runningTasksByHost[binding.hostAppId] ?? 0} 个。新 Task 生效规则：新 Run 使用目标版本；旧 Task 固定快照规则：进行中的旧 Task 保持创建时的版本快照直至结束（PRD 24.4）。`}
            irreversibility='回滚通过 Rollout 记录执行，不删除任何历史 Revision；可再次前滚。'
            currentRevision={`connector rev ${binding.connectorRevision} / manifest rev ${binding.manifestRevision}`}
            targetRevision={`connector rev ${targetRevision} / manifest rev ${Math.max(1, binding.manifestRevision - 1)}`}
            actionLabel='确认回滚'
            onConfirm={(reason) =>
              toast.success('回滚请求已提交（演示）', {
                description: `${binding.namespace} · 审计原因：${reason}`
              })
            }
          />
        );
      }
    }
  ];

  const spec = {
    textFilters: {
      hostAppId: (row: NamespaceBinding) => row.hostAppId,
      namespace: (row: NamespaceBinding) => row.namespace
    } satisfies Record<string, (row: NamespaceBinding) => string>,
    selectFilters: {
      status: (row: NamespaceBinding) => row.status,
      environment: (row: NamespaceBinding) => row.environment
    } satisfies Record<string, (row: NamespaceBinding) => string>,
    sortAccessors: {
      hostAppId: (row: NamespaceBinding) => row.hostAppId,
      namespace: (row: NamespaceBinding) => row.namespace,
      connectorRevision: (row: NamespaceBinding) => row.connectorRevision,
      manifestRevision: (row: NamespaceBinding) => row.manifestRevision,
      expectedRevision: (row: NamespaceBinding) => row.expectedRevision,
      updatedAt: (row: NamespaceBinding) => row.updatedAt
    } satisfies Record<string, (row: NamespaceBinding) => string | number>
  };

  const { table, total } = useMockDataTable({ rows: bindings, columns, spec });

  return (
    <div className='flex flex-1 flex-col gap-4'>
      <div className='flex items-center justify-between gap-2'>
        <p className='text-muted-foreground px-1 text-sm'>共 {total} 个 Namespace Binding</p>
        <Button onClick={() => setCreateOpen(true)}>
          <Icons.add data-icon='inline-start' />
          新建 Binding
        </Button>
      </div>
      <DataTable table={table}>
        <DataTableToolbar table={table} />
      </DataTable>
      <CreateBindingDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        hosts={hosts}
        agentReleases={agentReleases}
      />
    </div>
  );
}
