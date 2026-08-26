'use client';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DataList } from '@/components/platform/data-list';
import { DigestTag } from '@/components/platform/mono-id';
import { JsonBlock } from '@/components/platform/json-block';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { Icons } from '@/components/icons';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import type { PolicyRecord } from '@/lib/platform/types';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

const KIND_LABELS: Record<PolicyRecord['kind'], string> = {
  capability: 'Capability 能力',
  model: 'Model 模型',
  tool: 'Tool 工具',
  runtime: 'Runtime 运行时',
  network: 'Network 网络',
  approval: 'Approval 审批',
  'client-action': 'Client Action 前端动作',
  memory: 'Memory 记忆',
  artifact: 'Artifact 产物'
};

const LEVEL_LABELS: Record<PolicyRecord['level'], string> = {
  platform: 'Platform',
  environment: 'Environment',
  host: 'Host',
  namespace: 'Namespace',
  'agent-release': 'Agent Release',
  'task-type': 'Task Type',
  'frontend-profile': 'Frontend Profile'
};

const STATUS_LABELS: Record<PolicyRecord['status'], string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

const HIERARCHY: PolicyRecord['level'][] = [
  'platform',
  'environment',
  'host',
  'namespace',
  'agent-release',
  'task-type',
  'frontend-profile'
];

const KIND_SPEC_SAMPLE: Record<PolicyRecord['kind'], Record<string, unknown>> = {
  capability: { ceiling: 'namespace capability ceiling', overrides: ['tool.allow', 'client_action.confirm'] },
  model: { routeByRole: { coder: 'deepseek-chat', reviewer: 'deepseek-reasoner' }, fallback: 'deny' },
  tool: { allowlist: ['*.read'], denylist: ['*.write'], requireGrant: true },
  runtime: { sandbox: 'standard', timeoutSeconds: 900, egress: 'restricted' },
  network: { egressAllowlist: ['pypi.internal', 'models.internal'], default: 'deny' },
  approval: { riskLevels: ['high'], approvers: ['platform-owner'], timeout: 'expire+reject' },
  'client-action': { confirm: ['user_interaction'], fence: 'controller-lease-v2' },
  memory: { retentionDays: 30, redact: ['secret', 'credential_ref'] },
  artifact: { retentionDays: 90, maxSizeBytes: 52428800 }
};

function sampleContent(policy: PolicyRecord) {
  return {
    apiVersion: 'zebra.platform/v1',
    kind: `Policy/${policy.kind}`,
    metadata: {
      name: policy.name,
      level: policy.level,
      scope: policy.scope,
      revision: policy.revision,
      digest: `sha256:${policy.digest}`,
      status: policy.status,
      updatedBy: policy.updatedBy,
      updatedAt: policy.updatedAt
    },
    spec: KIND_SPEC_SAMPLE[policy.kind]
  };
}

type Filter = string;

export function PolicyTable({ policies }: { policies: PolicyRecord[] }) {
  const [kindFilter, setKindFilter] = useState<Filter>('all');
  const [levelFilter, setLevelFilter] = useState<Filter>('all');
  const [statusFilter, setStatusFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<PolicyRecord | null>(null);

  const filtered = useMemo(
    () =>
      policies.filter(
        (policy) =>
          (kindFilter === 'all' || policy.kind === kindFilter) &&
          (levelFilter === 'all' || policy.level === levelFilter) &&
          (statusFilter === 'all' || policy.status === statusFilter)
      ),
    [policies, kindFilter, levelFilter, statusFilter]
  );

  return (
    <div className='flex flex-col gap-4'>
      <Alert>
        <Icons.policy />
        <AlertTitle>Policy 层级与版本语义</AlertTitle>
        <AlertDescription className='space-y-1.5'>
          <div className='flex flex-wrap items-center gap-1 text-xs'>
            {HIERARCHY.map((level, index) => (
              <span key={level} className='flex items-center gap-1'>
                {index > 0 && <Icons.arrowRight className='text-muted-foreground/60 size-3' />}
                <Badge variant='outline' className='px-1.5 py-0 text-[11px]'>
                  {LEVEL_LABELS[level]}
                </Badge>
              </span>
            ))}
          </div>
          <p>
            低层级 Policy 可收窄（narrow）高层级授权，不能放大；已发布版本不可变，任何修改都会创建新
            Revision 并生成新 Digest。
          </p>
        </AlertDescription>
      </Alert>

      <div className='flex flex-wrap items-center gap-2'>
        <Select value={kindFilter} onValueChange={(value) => setKindFilter(value ?? 'all')}>
          <SelectTrigger size='sm' className='w-40'>
            <SelectValue placeholder='Kind' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部 Kind</SelectItem>
              {(Object.keys(KIND_LABELS) as PolicyRecord['kind'][]).map((kind) => (
                <SelectItem key={kind} value={kind}>
                  {KIND_LABELS[kind]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select value={levelFilter} onValueChange={(value) => setLevelFilter(value ?? 'all')}>
          <SelectTrigger size='sm' className='w-40'>
            <SelectValue placeholder='Level' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部 Level</SelectItem>
              {HIERARCHY.map((level) => (
                <SelectItem key={level} value={level}>
                  {LEVEL_LABELS[level]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value ?? 'all')}>
          <SelectTrigger size='sm' className='w-36'>
            <SelectValue placeholder='Status' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部状态</SelectItem>
              {(Object.keys(STATUS_LABELS) as PolicyRecord['status'][]).map((status) => (
                <SelectItem key={status} value={status}>
                  {STATUS_LABELS[status]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <span className='text-muted-foreground text-xs'>{filtered.length} 条 Policy</span>
        <div className='ml-auto'>
          <Button
            size='sm'
            onClick={() =>
              toast.success('Policy Draft 已创建（演示）', {
                description: 'Draft 进入 review 流程；发布后版本不可变，修改将创建新 Revision'
              })
            }
          >
            <Icons.plusCircle />
            新建 Policy Draft
          </Button>
        </div>
      </div>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted sticky top-0'>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Level</TableHead>
              <TableHead>Scope</TableHead>
              <TableHead className='text-right'>Revision</TableHead>
              <TableHead>Digest</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated By</TableHead>
              <TableHead>Updated At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((policy) => (
              <TableRow key={policy.id} className='cursor-pointer' onClick={() => setSelected(policy)}>
                <TableCell className='font-medium'>{policy.name}</TableCell>
                <TableCell>
                  <Badge variant='outline' className='text-xs'>
                    {KIND_LABELS[policy.kind]}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge variant='secondary' className='text-xs'>
                    {LEVEL_LABELS[policy.level]}
                  </Badge>
                </TableCell>
                <TableCell className='font-mono text-xs whitespace-nowrap'>{policy.scope}</TableCell>
                <TableCell className='text-right font-mono text-xs'>r{policy.revision}</TableCell>
                <TableCell>
                  <DigestTag value={policy.digest} />
                </TableCell>
                <TableCell>
                  <StatusBadge tone={lifecycleTone(policy.status)}>{STATUS_LABELS[policy.status]}</StatusBadge>
                </TableCell>
                <TableCell className='text-xs'>{policy.updatedBy}</TableCell>
                <TableCell className='text-muted-foreground text-xs whitespace-nowrap'>
                  {formatDateTime(policy.updatedAt)}
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className='text-muted-foreground h-24 text-center'>
                  没有匹配的 Policy
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className='max-h-[85vh] overflow-y-auto sm:max-w-2xl'>
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className='flex flex-wrap items-center gap-2'>
                  {selected.name}
                  <StatusBadge tone={lifecycleTone(selected.status)}>
                    {STATUS_LABELS[selected.status]}
                  </StatusBadge>
                </DialogTitle>
                <DialogDescription>
                  Policy 详情（{KIND_LABELS[selected.kind]} · {LEVEL_LABELS[selected.level]} 层级）
                </DialogDescription>
              </DialogHeader>
              <DataList
                columns={2}
                items={[
                  { label: 'Policy ID', value: <span className='font-mono text-xs'>{selected.id}</span> },
                  { label: 'Kind', value: KIND_LABELS[selected.kind] },
                  { label: 'Level', value: LEVEL_LABELS[selected.level] },
                  { label: 'Scope', value: <span className='font-mono text-xs'>{selected.scope}</span> },
                  { label: 'Revision', value: `r${selected.revision}` },
                  { label: 'Digest', value: <DigestTag value={selected.digest} /> },
                  { label: 'Updated By', value: selected.updatedBy },
                  { label: 'Updated At', value: formatDateTime(selected.updatedAt) }
                ]}
              />
              <JsonBlock title={`policy/${selected.id}.json`} value={sampleContent(selected)} />
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <p className='text-muted-foreground text-xs'>
                  已发布版本不可变；发布新版本将创建 r{selected.revision + 1} 并生成新 Digest。
                </p>
                <RiskConfirmDialog
                  trigger={<Button size='sm'>发布新版本</Button>}
                  title={`发布 ${selected.name}`}
                  impact={`${selected.scope} 作用域内全部 Agent Release 立即按新 Policy 评估`}
                  irreversibility='发布后不可回退到旧 Digest，只能再发布更新版本'
                  currentRevision={`r${selected.revision}`}
                  targetRevision={`r${selected.revision + 1}`}
                  actionLabel='确认发布'
                  onConfirm={() => undefined}
                />
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
