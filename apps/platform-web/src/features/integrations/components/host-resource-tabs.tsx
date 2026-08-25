'use client';

import Link from 'next/link';
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
import { Icons } from '@/components/icons';
import { DataList } from '@/components/platform/data-list';
import { DigestTag } from '@/components/platform/mono-id';
import { RiskBadge } from '@/components/platform/risk-badge';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime, formatBytes } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type {
  BackendManifest,
  Connector,
  FrontendProfile,
  Host,
  InboundTrust
} from '@/lib/platform/types';
import {
  CONNECTOR_HEALTH_LABELS,
  NAMESPACE_STRATEGY_LABELS,
  REVISION_STATUS_LABELS,
  TRUST_HEALTH_LABELS
} from '../lib/labels';

function DemoButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button variant='outline' size='sm' onClick={onClick}>
      {label}
    </Button>
  );
}

/** Inbound Trust 面板（PRD 10.2 / 13）：字段展示 + 演示性测试按钮 + Token 安全提示。 */
export function HostTrustTab({ trust }: { trust?: InboundTrust }) {
  if (!trust) {
    return (
      <Alert>
        <Icons.info />
        <AlertTitle>尚未配置入站信任</AlertTitle>
        <AlertDescription>
          通过接入向导第 2 步配置 Issuer / Audience / JWKS 后，此处会展示信任配置与健康状态。
        </AlertDescription>
      </Alert>
    );
  }

  const runDemo = (name: string) => toast.success(`${name} 已执行（演示）`, { description: '结果不会写回平台数据' });

  return (
    <div className='flex flex-col gap-4'>
      <Alert>
        <Icons.lock />
        <AlertTitle>平台不展示完整 Token</AlertTitle>
        <AlertDescription>
          验证仅返回解析结论与 Claim 摘要；完整 Token 内容不会出现在控制台或审计记录中（PRD 13.4）。
        </AlertDescription>
      </Alert>

      <Card className='py-0'>
        <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
          <CardTitle className='text-sm'>信任配置 rev {trust.revision}</CardTitle>
          <StatusBadge tone={lifecycleTone(trust.health)}>
            {TRUST_HEALTH_LABELS[trust.health]}
          </StatusBadge>
        </CardHeader>
        <CardContent className='space-y-4 p-4'>
          <DataList
            columns={2}
            items={[
              { label: 'Issuer', value: <span className='font-mono text-xs'>{trust.issuer}</span> },
              { label: 'Audience', value: <span className='font-mono text-xs'>{trust.audience}</span> },
              { label: 'JWKS URI', value: <span className='font-mono text-xs'>{trust.jwksUri}</span> },
              { label: 'Allowed Origins', value: trust.allowedOrigins.join('、') },
              { label: 'Algorithms', value: trust.algorithms.join('、') },
              { label: 'Policy Version', value: trust.policyVersion },
              {
                label: 'Namespace Strategy',
                value: NAMESPACE_STRATEGY_LABELS[trust.namespaceStrategy]
              },
              { label: 'Clock Skew', value: `${trust.clockSkewSeconds}s` },
              { label: 'Last Verified', value: formatDateTime(trust.lastVerifiedAt) },
              { label: 'Digest', value: <DigestTag value={trust.digest} /> },
              { label: 'Status', value: REVISION_STATUS_LABELS[trust.status] }
            ]}
          />
          <div className='flex flex-wrap gap-2 border-t pt-4'>
            <DemoButton label='Test JWKS' onClick={() => runDemo('Test JWKS')} />
            <DemoButton label='Verify Sample Grant' onClick={() => runDemo('Verify Sample Grant')} />
            <DemoButton label='Preview Parsed Claims' onClick={() => runDemo('Preview Parsed Claims')} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/** Outbound Connector 面板（PRD 11）：配置 DataList + 策略卡 + 详情链接。 */
export function HostConnectorTab({ connector }: { connector?: Connector }) {
  if (!connector) {
    return (
      <Alert>
        <Icons.info />
        <AlertTitle>尚未配置出站 Connector</AlertTitle>
        <AlertDescription>通过接入向导第 3 步登记 Connector 端点与引用后展示。</AlertDescription>
      </Alert>
    );
  }

  return (
    <Card className='py-0'>
      <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
        <CardTitle className='flex items-center gap-2 text-sm'>
          <Icons.connector className='size-4' />
          {connector.id}
        </CardTitle>
        <div className='flex items-center gap-2'>
          <StatusBadge tone={lifecycleTone(connector.health)}>
            {CONNECTOR_HEALTH_LABELS[connector.health]}
          </StatusBadge>
          <Button variant='outline' size='sm' render={<Link href={`/integrations/connectors/${connector.id}`} aria-label='查看 Connector 详情' />}>
            Connector 详情
            <Icons.chevronRight className='size-3.5' />
          </Button>
        </div>
      </CardHeader>
      <CardContent className='grid grid-cols-1 gap-4 p-4 lg:grid-cols-2'>
        <DataList
          columns={2}
          items={[
            { label: 'Base URI', value: <span className='font-mono text-xs'>{connector.baseUri}</span> },
            { label: 'Manifest Path', value: <span className='font-mono text-xs'>{connector.manifestPath}</span> },
            { label: 'Invoke Path', value: <span className='font-mono text-xs'>{connector.invokePath}</span> },
            { label: 'Reconcile Path', value: <span className='font-mono text-xs'>{connector.reconcilePath}</span> },
            { label: 'Protocol Versions', value: connector.protocolVersions.join('、') },
            { label: 'Workload Identity Ref', value: <span className='font-mono text-xs'>{connector.workloadIdentityRef}</span> },
            { label: 'Credential Ref', value: <span className='font-mono text-xs'>{connector.credentialRef}</span> },
            { label: 'Network Policy Ref', value: <span className='font-mono text-xs'>{connector.networkPolicyRef}</span> },
            { label: 'Latest Rev / Bound Rev', value: `rev ${connector.latestRevision} / rev ${connector.boundRevision}` }
          ]}
        />
        <div className='grid grid-cols-1 gap-3 sm:grid-cols-2'>
          <div className='bg-muted/40 rounded-lg border p-3'>
            <p className='text-muted-foreground text-xs font-medium'>Timeout Policy</p>
            <p className='mt-1 text-sm'>连接 {connector.timeoutPolicy.connectSeconds}s · 读取 {connector.timeoutPolicy.readSeconds}s</p>
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
  );
}

const TOOL_TABLE_HEADS = ['Tool', 'Capability', 'Risk', 'Idempotency', 'Timeout', 'Max Output', 'Reconcile'];

/** Backend Capabilities 面板（PRD 12）：manifest tool 契约表 + digest。 */
export function HostBackendTab({ manifest }: { manifest?: BackendManifest }) {
  if (!manifest) {
    return (
      <Alert>
        <Icons.info />
        <AlertTitle>尚未发布 Backend Manifest</AlertTitle>
        <AlertDescription>通过接入向导第 4 步提交并校验 Manifest 后展示。</AlertDescription>
      </Alert>
    );
  }

  return (
    <Card className='py-0'>
      <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
        <CardTitle className='flex items-center gap-2 text-sm'>
          <Icons.manifest className='size-4' />
          {manifest.id} · rev {manifest.revision}
        </CardTitle>
        <div className='flex items-center gap-2'>
          <DigestTag value={manifest.digest} />
          <Button
            variant='outline'
            size='sm'
            render={<Link href={`/integrations/backend-manifests/${manifest.id}`} aria-label='打开 Manifest 编辑器' />}
          >
            打开编辑器
          </Button>
        </div>
      </CardHeader>
      <CardContent className='p-0'>
        <Table>
          <TableHeader>
            <TableRow>
              {TOOL_TABLE_HEADS.map((head) => (
                <TableHead key={head}>{head}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {manifest.tools.map((tool) => (
              <TableRow key={tool.name}>
                <TableCell>
                  <p className='font-mono text-xs font-medium'>{tool.name}</p>
                  <p className='text-muted-foreground text-xs'>{tool.description}</p>
                </TableCell>
                <TableCell>
                  <span className='font-mono text-xs'>{tool.capability}</span>
                </TableCell>
                <TableCell>
                  <RiskBadge risk={tool.risk} />
                </TableCell>
                <TableCell className='text-xs'>
                  {tool.idempotency === 'none' ? '—' : tool.idempotency === 'idempotent' ? '幂等' : '幂等键'}
                </TableCell>
                <TableCell className='text-xs tabular-nums'>{tool.timeoutSeconds}s</TableCell>
                <TableCell className='text-xs tabular-nums'>{formatBytes(tool.maxOutputBytes)}</TableCell>
                <TableCell>
                  {tool.reconcileCapable ? (
                    <StatusBadge tone='success' withDot={false}>支持</StatusBadge>
                  ) : (
                    <span className='text-muted-foreground text-xs'>—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

/** Frontend Capabilities 面板（PRD 14）：profile 概要 + 跳转。 */
export function HostFrontendTab({
  frontendProfile,
  host
}: {
  frontendProfile?: FrontendProfile;
  host: Host;
}) {
  if (!frontendProfile) {
    return (
      <Alert>
        <Icons.info />
        <AlertTitle>尚未配置 Frontend Capability Profile</AlertTitle>
        <AlertDescription>
          Host {host.appId} 未绑定 Frontend Profile；纯后端接入可跳过该依赖。
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <Card className='py-0'>
      <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
        <CardTitle className='flex items-center gap-2 text-sm'>
          <Icons.frontend className='size-4' />
          {frontendProfile.frontendAppId} · rev {frontendProfile.revision}
        </CardTitle>
        <Button
          variant='outline'
          size='sm'
          render={<Link href={`/frontend/profiles/${frontendProfile.id}`} aria-label='查看 Frontend Profile 详情' />}
        >
          Frontend Profile 详情
          <Icons.chevronRight className='size-3.5' />
        </Button>
      </CardHeader>
      <CardContent className='p-4'>
        <DataList
          columns={3}
          items={[
            { label: 'Build ID', value: <span className='font-mono text-xs'>{frontendProfile.buildId}</span> },
            { label: 'Readables', value: `${frontendProfile.readables.length} 个` },
            { label: 'Actions', value: `${frontendProfile.actions.length} 个` },
            { label: 'Allowed Origins', value: frontendProfile.allowedOrigins.join('、') },
            { label: 'Mounted Clients', value: `${frontendProfile.mountedClients}` },
            { label: 'Digest', value: <DigestTag value={frontendProfile.digest} /> }
          ]}
        />
      </CardContent>
    </Card>
  );
}
