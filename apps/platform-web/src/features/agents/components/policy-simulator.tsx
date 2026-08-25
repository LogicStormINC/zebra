'use client';
import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
import { JsonBlock } from '@/components/platform/json-block';
import { Icons } from '@/components/icons';
import { formatNumber } from '@/lib/platform/format';
import type {
  AgentDefinition,
  AgentRelease,
  CapabilityProfile,
  Host,
  NamespaceBinding,
  PolicyRecord,
  Quota
} from '@/lib/platform/types';

export type PolicySimulatorData = {
  hosts: Host[];
  bindings: NamespaceBinding[];
  releases: AgentRelease[];
  definitions: AgentDefinition[];
  capabilityProfiles: CapabilityProfile[];
  quotas: Quota[];
  policies: PolicyRecord[];
};

type SimulationResult = ReturnType<typeof simulate>;

/** Effective Policy Simulator（PRD 15.2）：静态推导 Host × Namespace × Agent Release 的合成策略。 */
export function PolicySimulator({ data }: { data: PolicySimulatorData }) {
  const [hostId, setHostId] = useState<string>(data.hosts[0]?.id ?? '');
  const [namespace, setNamespace] = useState<string>('');
  const [releaseId, setReleaseId] = useState<string>(data.releases[0]?.id ?? '');
  const [result, setResult] = useState<SimulationResult | null>(null);

  const hostBindings = data.bindings.filter((binding) => binding.hostAppId === hostId);
  const effectiveNamespace = namespace || hostBindings[0]?.namespace || '';

  const run = () => {
    setResult(
      simulate({
        ...data,
        hostId,
        namespace: effectiveNamespace,
        releaseId
      })
    );
  };

  return (
    <Card className='py-0'>
      <CardHeader className='border-b px-4 py-3'>
        <CardTitle className='flex items-center gap-2 text-sm'>
          <Icons.inspector className='size-4' />
          Effective Policy Simulator
        </CardTitle>
      </CardHeader>
      <CardContent className='flex flex-col gap-4 p-4'>
        <p className='text-muted-foreground text-xs'>
          选择 Host、Namespace 与 Agent Release，静态推导合成后的策略结果（演示：交集逻辑按所选 Release 的 Capability Ceiling 简化）。
        </p>
        <div className='flex flex-wrap items-end gap-3'>
          <div className='space-y-1'>
            <p className='text-muted-foreground text-xs'>Host</p>
            <Select
              items={Object.fromEntries(data.hosts.map((host) => [host.id, host.name]))}
              value={hostId}
              onValueChange={(value) => {
                setHostId(String(value));
                setNamespace('');
                setResult(null);
              }}
            >
              <SelectTrigger className='w-52'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {data.hosts.map((host) => (
                    <SelectItem key={host.id} value={host.id}>
                      {host.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1'>
            <p className='text-muted-foreground text-xs'>Namespace</p>
            <Select
              items={Object.fromEntries(hostBindings.map((binding) => [binding.namespace, binding.namespace]))}
              value={effectiveNamespace || null}
              onValueChange={(value) => {
                setNamespace(String(value));
                setResult(null);
              }}
            >
              <SelectTrigger className='w-52'>
                <SelectValue placeholder='选择 Namespace' />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {hostBindings.map((binding) => (
                    <SelectItem key={binding.id} value={binding.namespace}>
                      {binding.namespace}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1'>
            <p className='text-muted-foreground text-xs'>Agent Release</p>
            <Select
              items={Object.fromEntries(
                data.releases.map((release) => [release.id, `${release.definitionName} v${release.version} (${release.channel})`])
              )}
              value={releaseId || null}
              onValueChange={(value) => {
                setReleaseId(String(value));
                setResult(null);
              }}
            >
              <SelectTrigger className='w-64'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {data.releases.map((release) => (
                    <SelectItem key={release.id} value={release.id}>
                      {release.definitionName} v{release.version}（{release.channel}）
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <Button size='sm' onClick={run} disabled={!hostId || !effectiveNamespace || !releaseId}>
            模拟
          </Button>
        </div>

        {result ? <SimulationResultView result={result} /> : (
          <EmptyState
            icon='inspector'
            title='尚未运行模拟'
            description='选择输入后点击「模拟」，查看合成策略的推导结果'
          />
        )}
      </CardContent>
    </Card>
  );
}

function simulate(data: PolicySimulatorData & { hostId: string; namespace: string; releaseId: string }) {
  const host = data.hosts.find((item) => item.id === data.hostId || item.appId === data.hostId);
  const binding = data.bindings.find(
    (item) => item.hostAppId === data.hostId && item.namespace === data.namespace
  );
  const release = data.releases.find((item) => item.id === data.releaseId);
  const definition = release ? data.definitions.find((item) => item.id === release.definitionId) : undefined;
  const capabilityProfile = definition
    ? data.capabilityProfiles.find((item) => item.id === definition.toolProfileId)
    : undefined;
  const approvalPolicy = data.policies.find((item) => item.kind === 'approval');

  const rejectedReasons: string[] = [];
  if (!host) rejectedReasons.push('Host 不存在或已被撤销');
  if (!binding) rejectedReasons.push('该 Namespace 没有 Binding，未授权任何 Agent Release');
  if (binding && binding.status === 'rolled-back') rejectedReasons.push('Namespace Binding 已回滚，Release 不生效');
  if (binding && release && binding.agentReleaseId !== release.id) {
    rejectedReasons.push(`Binding 绑定的是 ${binding.agentReleaseId}，所选 Release 未授权给该 Namespace`);
  }
  if (release && release.status !== 'published') rejectedReasons.push('所选 Release 状态不是 published');

  return {
    hostName: host?.name ?? host?.appId ?? data.hostId,
    namespace: data.namespace,
    release,
    definition,
    capabilityProfile,
    effectiveCapabilities: definition?.capabilityCeiling ?? [],
    backendTools: capabilityProfile?.backendTools ?? [],
    clientActions: capabilityProfile?.clientActions ?? [],
    limits: data.quotas.slice(0, 4),
    approvalPolicy,
    rejectedReasons,
    bindingPreview: {
      host: { appId: host?.appId ?? data.hostId, manifestId: host?.manifestId ?? null, connectorRevision: host?.connectorRevision ?? null },
      namespace: data.namespace,
      binding: binding ? { id: binding.id, status: binding.status, expectedRevision: binding.expectedRevision } : null,
      agentRelease: release
        ? { id: release.id, definitionId: release.definitionId, version: release.version, digest: release.digest, channel: release.channel }
        : null,
      capabilityProfile: capabilityProfile
        ? { id: capabilityProfile.id, revision: capabilityProfile.revision, digest: capabilityProfile.digest }
        : null
    }
  };
}

function SimulationResultView({ result }: { result: SimulationResult }) {
  return (
    <div className='flex flex-col gap-4'>
      <div className='grid grid-cols-1 gap-3 lg:grid-cols-2'>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-2.5'>
            <CardTitle className='text-sm'>Effective Capabilities</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            <div className='flex flex-wrap gap-1.5'>
              {result.effectiveCapabilities.map((capability) => (
                <Badge key={capability} variant='secondary' className='font-mono text-xs'>
                  {capability}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-2.5'>
            <CardTitle className='text-sm'>Effective Backend Tools</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            <ul className='space-y-1 text-sm'>
              {result.backendTools.map((tool) => (
                <li key={tool} className='flex items-center gap-2'>
                  <Icons.connector className='text-muted-foreground size-3.5' />
                  <span className='font-mono text-xs'>{tool}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-2.5'>
            <CardTitle className='text-sm'>Effective Client Actions</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            {result.clientActions.length === 0 ? (
              <p className='text-muted-foreground text-sm'>该 Release 无前端动作</p>
            ) : (
              <ul className='space-y-1 text-sm'>
                {result.clientActions.map((action) => (
                  <li key={action} className='flex items-center gap-2'>
                    <Icons.clientEffect className='text-muted-foreground size-3.5' />
                    <span className='font-mono text-xs'>{action}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-2.5'>
            <CardTitle className='text-sm'>Required Approvals</CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            {result.approvalPolicy ? (
              <div className='space-y-1 text-sm'>
                <p>
                  <span className='font-medium'>{result.approvalPolicy.name}</span>
                  <span className='text-muted-foreground'>（rev {result.approvalPolicy.revision}）</span>
                </p>
                <p className='text-muted-foreground text-xs'>
                  高风险写操作（risk=high）执行前需要操作员审批；本模拟输入下命中的审批策略如上。
                </p>
              </div>
            ) : (
              <p className='text-muted-foreground text-sm'>未配置审批策略</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-2.5'>
          <CardTitle className='text-sm'>Effective Limits</CardTitle>
        </CardHeader>
        <CardContent className='p-0'>
          <Table>
            <TableHeader className='bg-muted'>
              <TableRow>
                <TableHead>Dimension</TableHead>
                <TableHead>Soft Limit</TableHead>
                <TableHead>Hard Limit</TableHead>
                <TableHead>Used</TableHead>
                <TableHead>Reset Cycle</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.limits.map((quota) => (
                <TableRow key={quota.id}>
                  <TableCell className='font-mono text-xs'>{quota.dimension}</TableCell>
                  <TableCell className='tabular-nums'>{formatNumber(quota.softLimit)}</TableCell>
                  <TableCell className='tabular-nums'>{formatNumber(quota.hardLimit)}</TableCell>
                  <TableCell className='tabular-nums'>{formatNumber(quota.used)}</TableCell>
                  <TableCell className='text-sm'>{quota.resetCycle}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-2.5'>
          <CardTitle className='text-sm'>Rejected Reasons</CardTitle>
        </CardHeader>
        <CardContent className='p-4'>
          {result.rejectedReasons.length === 0 ? (
            <p className='flex items-center gap-2 text-sm'>
              <Icons.check className='text-emerald-600 size-4' />
              无拒绝项
            </p>
          ) : (
            <ul className='space-y-1 text-sm'>
              {result.rejectedReasons.map((reason) => (
                <li key={reason} className='flex items-center gap-2'>
                  <Icons.close className='text-destructive size-4' />
                  {reason}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div>
        <p className='text-muted-foreground mb-1.5 text-xs font-medium'>Binding Preview</p>
        <JsonBlock title='binding-preview.json' value={result.bindingPreview} maxHeight={280} />
      </div>
    </div>
  );
}
