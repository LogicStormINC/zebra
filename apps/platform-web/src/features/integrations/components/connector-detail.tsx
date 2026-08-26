'use client';

import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Icons } from '@/components/icons';
import { DataList } from '@/components/platform/data-list';
import { EmptyState } from '@/components/platform/empty-state';
import { JsonBlock } from '@/components/platform/json-block';
import { MonoId } from '@/components/platform/mono-id';
import { PageHeader } from '@/components/platform/page-header';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime, relativeTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { AuditEntry, Connector, NamespaceBinding } from '@/lib/platform/types';
import {
  BINDING_STATUS_LABELS,
  CONNECTOR_HEALTH_LABELS,
  REVISION_STATUS_LABELS
} from '../lib/labels';
import { ConnectorVersionsTab } from './connector-versions-tab';

const HEALTH_CHECK_ITEMS = [
  {
    key: 'endpoint',
    label: 'Endpoint Health',
    description: 'Invoke 端点探活（2xx/4xx 均视为可达）'
  },
  { key: 'tls', label: 'TLS', description: '证书链与最低版本（TLS 1.2+）' },
  {
    key: 'manifest',
    label: 'Manifest Fetch',
    description: '从 manifestPath 拉取能力清单并校验 digest'
  },
  { key: 'credential', label: 'Credential Ref', description: '引用可达且可换取短期凭据' },
  { key: 'network', label: 'Network Policy', description: '出站 egress 与策略引用一致' }
] as const;

/** Connector 详情（PRD 11）：配置、版本、健康检查、凭据引用、网络策略与审计。 */
export function ConnectorDetail({
  connector,
  bindings,
  auditEntries
}: {
  connector: Connector;
  bindings: NamespaceBinding[];
  auditEntries: AuditEntry[];
}) {
  const checkHealth = (key: string): 'healthy' | 'degraded' => {
    if (connector.health === 'healthy') return 'healthy';
    // degraded/unreachable 时按检查项性质给出确定的降级结论（演示推导）
    if (key === 'endpoint' || key === 'manifest')
      return connector.health === 'unreachable' ? 'degraded' : 'healthy';
    if (key === 'credential' && connector.health === 'degraded') return 'degraded';
    return 'healthy';
  };

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title={
          <span className='flex flex-wrap items-center gap-2'>
            <span className='font-mono'>{connector.id}</span>
            <MonoId value={connector.hostAppId} head={6} tail={0} prefix='host:' copyable={false} />
            <StatusBadge tone={lifecycleTone(connector.health)}>
              {CONNECTOR_HEALTH_LABELS[connector.health]}
            </StatusBadge>
            <StatusBadge tone={lifecycleTone(connector.status)} withDot={false}>
              {REVISION_STATUS_LABELS[connector.status]}
            </StatusBadge>
          </span>
        }
        description={`出站 Connector · latest rev ${connector.latestRevision} / bound rev ${connector.boundRevision} · 更新于 ${relativeTime(connector.updatedAt)}`}
        actions={
          <RiskConfirmDialog
            trigger={
              <Button variant='destructive'>
                <Icons.warning data-icon='inline-start' />
                Revoke Connector
              </Button>
            }
            title={`Revoke Connector ${connector.id}`}
            impact={`受影响 Host：${connector.hostAppId}（1 个）；受影响 Namespace：${bindings.length} 个；运行中 Task：6 个；等待中 Client Effect：2 个；最近 24h 调用量：1,284 次。`}
            irreversibility='Revoke 立即 fail closed：新调用被拒绝，运行中调用按超时策略收敛；不可恢复为 published。'
            currentRevision={`rev ${connector.latestRevision}`}
            actionLabel='确认 Revoke'
            onConfirm={(reason) =>
              toast.success('Revoke 请求已记录（演示）', { description: `审计原因：${reason}` })
            }
          />
        }
        meta={
          <div className='flex flex-wrap items-center gap-x-4 gap-y-1.5'>
            <span>
              Base URI：<span className='font-mono'>{connector.baseUri}</span>
            </span>
            <span>Protocol：{connector.protocolVersions.join('、')}</span>
            <span>
              Digest：<span className='font-mono'>{connector.digest.slice(0, 12)}…</span>
            </span>
            <span>Updated：{formatDateTime(connector.updatedAt)}</span>
          </div>
        }
      />

      <div className='flex flex-1 flex-col gap-4 p-4 md:px-6'>
        <Tabs defaultValue='overview' className='w-full'>
          <TabsList className='flex h-auto w-full flex-wrap'>
            <TabsTrigger value='overview'>Overview</TabsTrigger>
            <TabsTrigger value='versions'>Versions</TabsTrigger>
            <TabsTrigger value='bindings'>Namespace Bindings</TabsTrigger>
            <TabsTrigger value='health'>Health Checks</TabsTrigger>
            <TabsTrigger value='manifest'>Manifest</TabsTrigger>
            <TabsTrigger value='credential'>Credential Reference</TabsTrigger>
            <TabsTrigger value='network'>Network Policy</TabsTrigger>
            <TabsTrigger value='audit'>Audit</TabsTrigger>
          </TabsList>

          <TabsContent value='overview' className='mt-4'>
            <Card className='py-0'>
              <CardContent className='grid grid-cols-1 gap-4 p-4 lg:grid-cols-2'>
                <DataList
                  columns={2}
                  items={[
                    { label: 'Host App ID', value: connector.hostAppId },
                    {
                      label: 'Base URI',
                      value: <span className='font-mono text-xs'>{connector.baseUri}</span>
                    },
                    {
                      label: 'Manifest Path',
                      value: <span className='font-mono text-xs'>{connector.manifestPath}</span>
                    },
                    {
                      label: 'Invoke Path',
                      value: <span className='font-mono text-xs'>{connector.invokePath}</span>
                    },
                    {
                      label: 'Reconcile Path',
                      value: <span className='font-mono text-xs'>{connector.reconcilePath}</span>
                    },
                    { label: 'Protocol Versions', value: connector.protocolVersions.join('、') },
                    {
                      label: 'Workload Identity Ref',
                      value: (
                        <span className='font-mono text-xs'>{connector.workloadIdentityRef}</span>
                      )
                    },
                    {
                      label: 'Credential Ref',
                      value: <span className='font-mono text-xs'>{connector.credentialRef}</span>
                    },
                    {
                      label: 'Network Policy Ref',
                      value: <span className='font-mono text-xs'>{connector.networkPolicyRef}</span>
                    },
                    {
                      label: 'Latest / Bound Rev',
                      value: `rev ${connector.latestRevision} / rev ${connector.boundRevision}`
                    },
                    {
                      label: 'Digest',
                      value: <span className='font-mono text-xs'>{connector.digest}</span>
                    }
                  ]}
                />
                <div className='flex flex-col gap-3'>
                  <div className='bg-muted/40 rounded-lg border p-3'>
                    <p className='text-muted-foreground text-xs font-medium'>Timeout Policy</p>
                    <p className='mt-1 text-sm'>
                      连接 {connector.timeoutPolicy.connectSeconds}s · 读取{' '}
                      {connector.timeoutPolicy.readSeconds}s
                    </p>
                  </div>
                  <div className='bg-muted/40 rounded-lg border p-3'>
                    <p className='text-muted-foreground text-xs font-medium'>Retry Policy</p>
                    <p className='mt-1 text-sm'>
                      最多 {connector.retryPolicy.maxRetries} 次 ·{' '}
                      {connector.retryPolicy.backoff === 'exponential' ? '指数退避' : '固定间隔'}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value='versions' className='mt-4'>
            <ConnectorVersionsTab connector={connector} bindingsCount={bindings.length} />
          </TabsContent>

          <TabsContent value='bindings' className='mt-4'>
            <Card className='py-0'>
              <CardHeader className='border-b px-4 py-3'>
                <CardTitle className='text-sm'>
                  引用该 Connector 的 Namespace Binding（{bindings.length}）
                </CardTitle>
              </CardHeader>
              <CardContent className='p-0'>
                {bindings.length === 0 ? (
                  <p className='text-muted-foreground px-4 py-3 text-sm'>
                    暂无绑定引用该 Connector。
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Namespace</TableHead>
                        <TableHead>Connector Rev</TableHead>
                        <TableHead>Expected Revision</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Updated At</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {bindings.map((binding) => (
                        <TableRow key={binding.id}>
                          <TableCell className='font-mono text-xs'>{binding.namespace}</TableCell>
                          <TableCell className='tabular-nums'>
                            rev {binding.connectorRevision}
                          </TableCell>
                          <TableCell className='tabular-nums'>{binding.expectedRevision}</TableCell>
                          <TableCell>
                            <StatusBadge
                              tone={lifecycleTone(
                                binding.status === 'active' ? 'active' : 'pending'
                              )}
                              withDot={false}
                            >
                              {BINDING_STATUS_LABELS[binding.status]}
                            </StatusBadge>
                          </TableCell>
                          <TableCell className='text-muted-foreground text-xs'>
                            {formatDateTime(binding.updatedAt)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value='health' className='mt-4'>
            <div className='flex flex-col gap-4'>
              <div className='flex justify-end'>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => toast.success('健康检查已重新执行（演示）')}
                >
                  重新执行检查
                </Button>
              </div>
              <div className='grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3'>
                {HEALTH_CHECK_ITEMS.map((item) => {
                  const status = checkHealth(item.key);
                  return (
                    <Card key={item.key} className='py-0'>
                      <CardContent className='space-y-1.5 p-4'>
                        <div className='flex items-center justify-between gap-2'>
                          <p className='text-sm font-medium'>{item.label}</p>
                          <StatusBadge
                            tone={status === 'healthy' ? 'success' : 'warning'}
                            withDot={false}
                          >
                            {CONNECTOR_HEALTH_LABELS[status] ?? status}
                          </StatusBadge>
                        </div>
                        <p className='text-muted-foreground text-xs'>{item.description}</p>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </div>
          </TabsContent>

          <TabsContent value='manifest' className='mt-4'>
            <Card className='py-0'>
              <CardHeader className='border-b px-4 py-3'>
                <CardTitle className='text-sm'>Manifest 端点信息</CardTitle>
              </CardHeader>
              <CardContent className='space-y-3 p-4'>
                <DataList
                  columns={3}
                  items={[
                    {
                      label: 'Fetch URL',
                      value: (
                        <span className='font-mono text-xs'>
                          {connector.baseUri}
                          {connector.manifestPath}
                        </span>
                      )
                    },
                    { label: 'Protocol Versions', value: connector.protocolVersions.join('、') },
                    { label: 'Last Fetch', value: formatDateTime(connector.updatedAt) }
                  ]}
                />
                <JsonBlock
                  title='最近一次拉取的 Manifest 响应（演示）'
                  value={{
                    protocolVersion: connector.protocolVersions[0],
                    tools: [
                      { name: 'sample.read', risk: 'read', idempotency: 'none' },
                      { name: 'sample.write', risk: 'high', idempotency: 'idempotency_key' }
                    ],
                    digest: connector.digest
                  }}
                  maxHeight={240}
                />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value='credential' className='mt-4'>
            <div className='flex flex-col gap-4'>
              <Alert>
                <Icons.lock />
                <AlertTitle>平台不显示明文凭据</AlertTitle>
                <AlertDescription>
                  平台仅保存 Credential Ref，运行时通过 Credential Provider 换取短期凭据；
                  明文凭据不落控制台、日志与审计（PRD 6.5）。
                </AlertDescription>
              </Alert>
              <Card className='py-0'>
                <CardContent className='p-4'>
                  <DataList
                    columns={3}
                    items={[
                      {
                        label: 'Credential Ref',
                        value: (
                          <MonoId
                            value={connector.credentialRef}
                            head={14}
                            tail={6}
                            copyable={false}
                          />
                        )
                      },
                      { label: 'Provider', value: 'vault（演示）' },
                      { label: 'Rotation', value: '每 24 小时自动轮换' },
                      {
                        label: 'Health',
                        value: (
                          <StatusBadge
                            tone={checkHealth('credential') === 'healthy' ? 'success' : 'warning'}
                            withDot={false}
                          >
                            {checkHealth('credential') === 'healthy' ? '可用' : '降级'}
                          </StatusBadge>
                        )
                      },
                      { label: 'Last Rotation', value: formatDateTime(connector.updatedAt) },
                      { label: 'Scope', value: `${connector.hostAppId}/connector` }
                    ]}
                  />
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value='network' className='mt-4'>
            <Card className='py-0'>
              <CardContent className='p-4'>
                <DataList
                  columns={2}
                  items={[
                    {
                      label: 'Network Policy Ref',
                      value: <span className='font-mono text-xs'>{connector.networkPolicyRef}</span>
                    },
                    {
                      label: 'Egress Target',
                      value: <span className='font-mono text-xs'>{connector.baseUri}</span>
                    },
                    {
                      label: 'Workload Identity',
                      value: (
                        <span className='font-mono text-xs'>{connector.workloadIdentityRef}</span>
                      )
                    },
                    {
                      label: '策略状态',
                      value: (
                        <StatusBadge tone='success' withDot={false}>
                          已生效
                        </StatusBadge>
                      )
                    }
                  ]}
                />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value='audit' className='mt-4'>
            <Card className='py-0'>
              <CardHeader className='border-b px-4 py-3'>
                <CardTitle className='text-sm'>相关审计（{auditEntries.length}）</CardTitle>
              </CardHeader>
              <CardContent className='p-0'>
                {auditEntries.length === 0 ? (
                  <p className='text-muted-foreground px-4 py-3 text-sm'>
                    暂无该 Host 的审计记录。
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>时间</TableHead>
                        <TableHead>Actor</TableHead>
                        <TableHead>Action</TableHead>
                        <TableHead>Resource</TableHead>
                        <TableHead>结果</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {auditEntries.map((entry) => (
                        <TableRow key={entry.id}>
                          <TableCell className='text-muted-foreground text-xs'>
                            {formatDateTime(entry.timestamp)}
                          </TableCell>
                          <TableCell className='text-xs'>{entry.actor}</TableCell>
                          <TableCell className='font-mono text-xs'>{entry.action}</TableCell>
                          <TableCell className='font-mono text-xs'>
                            {entry.resourceType}/{entry.resourceId}
                          </TableCell>
                          <TableCell>
                            <StatusBadge tone={lifecycleTone(entry.result)} withDot={false}>
                              {entry.result === 'succeeded'
                                ? '成功'
                                : entry.result === 'failed'
                                  ? '失败'
                                  : '拒绝'}
                            </StatusBadge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

/** Connector 不存在时的空态。 */
export function ConnectorNotFound({ connectorId }: { connectorId: string }) {
  return (
    <div className='flex flex-1 flex-col'>
      <EmptyState
        title='未找到该 Connector'
        description={`Connector ${connectorId} 不存在，请从列表重新进入`}
        icon='connector'
      />
    </div>
  );
}
