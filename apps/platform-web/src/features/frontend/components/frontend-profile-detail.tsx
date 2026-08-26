'use client';

import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DataList } from '@/components/platform/data-list';
import { DigestTag } from '@/components/platform/mono-id';
import { KpiCard } from '@/components/platform/kpi-card';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type {
  AuditEntry,
  ConformanceRun,
  FrontendProfile,
  MountedCapabilitySnapshot,
  PolicyRecord
} from '@/lib/platform/types';
import { HookCodePanel } from './hook-code-panel';
import { ProfileActionsTab, ProfileComponentsTab, ProfileReadablesTab } from './profile-contract-tabs';
import {
  ProfileAuditTab,
  ProfileConformanceTab,
  ProfileMountedSnapshotTab
} from './profile-runtime-tabs';
import { CONFORMANCE_LABELS, CONFORMANCE_TONES, PROFILE_STATUS_LABELS } from './labels';

const TABS = [
  { value: 'overview', label: 'Overview' },
  { value: 'readables', label: 'Readables' },
  { value: 'actions', label: 'Actions' },
  { value: 'components', label: 'Components' },
  { value: 'origins', label: 'Origins 与 Build' },
  { value: 'hook-code', label: 'Hook Code' },
  { value: 'mounted', label: 'Mounted Snapshot' },
  { value: 'client-policy', label: 'Client Policy' },
  { value: 'versions', label: 'Versions' },
  { value: 'conformance', label: 'Conformance' },
  { value: 'audit', label: 'Audit' }
] as const;

/**
 * Frontend Profile 详情（PRD 13.3）：
 * 十一个视图覆盖契约、构建、挂载、策略、版本、质量与审计。
 */
export function FrontendProfileDetail({
  profile,
  snapshots,
  conformanceRuns,
  audits,
  policy
}: {
  profile: FrontendProfile;
  snapshots: MountedCapabilitySnapshot[];
  conformanceRuns: ConformanceRun[];
  audits: AuditEntry[];
  policy: PolicyRecord | null;
}) {
  const revisions = Array.from({ length: profile.revision }, (_, index) => profile.revision - index);

  return (
    <Tabs defaultValue='overview' className='gap-4'>
      <TabsList variant='line' className='flex-wrap'>
        {TABS.map((tab) => (
          <TabsTrigger key={tab.value} value={tab.value}>
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>

      <TabsContent value='overview' className='flex flex-col gap-4'>
        <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
          <Card className='py-0'>
            <CardHeader className='border-b px-4 py-3'>
              <CardTitle className='text-sm'>基础信息</CardTitle>
            </CardHeader>
            <CardContent className='px-4 py-4'>
              <DataList
                columns={2}
                items={[
                  { label: 'Host App ID', value: profile.hostAppId },
                  { label: 'Frontend App ID', value: profile.frontendAppId },
                  { label: 'Profile Revision', value: `rev ${profile.revision}` },
                  { label: 'Build ID', value: <span className='font-mono text-xs'>{profile.buildId}</span> },
                  { label: 'Digest', value: <DigestTag value={profile.digest} /> },
                  {
                    label: 'Status',
                    value: (
                      <StatusBadge tone={lifecycleTone(profile.status)}>
                        {PROFILE_STATUS_LABELS[profile.status]}
                      </StatusBadge>
                    )
                  },
                  { label: 'Mounted Clients', value: profile.mountedClients },
                  {
                    label: 'Conformance',
                    value: (
                      <StatusBadge tone={CONFORMANCE_TONES[profile.conformance]} withDot={false}>
                        {CONFORMANCE_LABELS[profile.conformance]}
                      </StatusBadge>
                    )
                  },
                  { label: '更新时间', value: formatDateTime(profile.updatedAt) }
                ]}
              />
            </CardContent>
          </Card>
          <div className='grid grid-cols-2 gap-4'>
            <KpiCard label='Readables' value={profile.readables.length} icon='eyeOff' hint='声明的前端上下文契约' />
            <KpiCard label='Actions' value={profile.actions.length} icon='clientEffect' hint='声明的客户端行为契约' />
            <KpiCard label='Components' value={profile.components.length} icon='code' hint='注册式组件' />
            <KpiCard label='Mounted Clients' value={profile.mountedClients} icon='clientSession' hint='当前挂载客户端数' />
          </div>
        </div>
      </TabsContent>

      <TabsContent value='readables'>
        <ProfileReadablesTab profile={profile} />
      </TabsContent>
      <TabsContent value='actions'>
        <ProfileActionsTab profile={profile} />
      </TabsContent>
      <TabsContent value='components'>
        <ProfileComponentsTab profile={profile} />
      </TabsContent>

      <TabsContent value='origins' className='flex flex-col gap-4'>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>Allowed Origins 与 Build</CardTitle>
            <CardDescription>
              运行时严格校验浏览器 Origin 与 Build ID，任何不匹配都会拒绝会话建立。
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-4 px-4 py-4'>
            <div className='space-y-1.5'>
              <p className='text-muted-foreground text-xs'>Allowed Origins</p>
              <div className='flex flex-wrap gap-1.5'>
                {profile.allowedOrigins.length === 0 ? (
                  <span className='text-muted-foreground text-sm'>—</span>
                ) : (
                  profile.allowedOrigins.map((origin) => (
                    <Badge key={origin} variant='secondary' className='font-mono text-xs'>
                      {origin}
                    </Badge>
                  ))
                )}
              </div>
            </div>
            <DataList
              columns={2}
              items={[
                { label: 'Build ID', value: <span className='font-mono text-xs'>{profile.buildId}</span> },
                { label: 'Profile Digest', value: <DigestTag value={profile.digest} /> },
                {
                  label: 'Origin 校验状态',
                  value: (
                    <StatusBadge tone={profile.status === 'published' ? 'success' : 'waiting'} withDot={false}>
                      {profile.status === 'published' ? '校验通过' : '待发布验证'}
                    </StatusBadge>
                  )
                },
                {
                  label: 'Build 校验状态',
                  value: (
                    <StatusBadge tone={snapshots.some((s) => s.frontendBuild === profile.buildId) ? 'success' : 'waiting'} withDot={false}>
                      {snapshots.some((s) => s.frontendBuild === profile.buildId) ? '与挂载一致' : '暂无挂载比对'}
                    </StatusBadge>
                  )
                }
              ]}
            />
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value='hook-code'>
        <HookCodePanel profile={profile} />
      </TabsContent>

      <TabsContent value='mounted'>
        <ProfileMountedSnapshotTab profile={profile} snapshots={snapshots} />
      </TabsContent>

      <TabsContent value='client-policy' className='flex flex-col gap-4'>
        {policy ? (
          <Card className='py-0'>
            <CardHeader className='border-b px-4 py-3'>
              <div className='flex items-center justify-between gap-2'>
                <CardTitle className='text-sm'>{policy.name}</CardTitle>
                <Link
                  href='/governance/policies'
                  className='text-primary hover:underline text-xs'
                >
                  在 Governance / Policy 中查看 →
                </Link>
              </div>
              <CardDescription className='font-mono text-xs'>
                {policy.id} · kind={policy.kind} · level={policy.level}
              </CardDescription>
            </CardHeader>
            <CardContent className='px-4 py-4'>
              <DataList
                columns={2}
                items={[
                  { label: 'Scope', value: <span className='font-mono text-xs'>{policy.scope}</span> },
                  { label: 'Revision', value: `rev ${policy.revision}` },
                  { label: 'Digest', value: <DigestTag value={policy.digest} /> },
                  {
                    label: 'Status',
                    value: (
                      <StatusBadge tone={lifecycleTone(policy.status)} withDot={false}>
                        {PROFILE_STATUS_LABELS[policy.status]}
                      </StatusBadge>
                    )
                  },
                  { label: 'Updated By', value: policy.updatedBy },
                  { label: 'Updated At', value: formatDateTime(policy.updatedAt) }
                ]}
              />
            </CardContent>
          </Card>
        ) : (
          <Card className='py-0'>
            <CardContent className='text-muted-foreground px-4 py-6 text-sm'>
              该 Profile 尚未绑定 Client Action Policy（如 pol_client_action_trench）。
            </CardContent>
          </Card>
        )}
      </TabsContent>

      <TabsContent value='versions' className='flex flex-col gap-4'>
        <div className='overflow-x-auto rounded-lg border'>
          <Table>
            <TableHeader className='bg-muted'>
              <TableRow>
                <TableHead>Revision</TableHead>
                <TableHead>Digest</TableHead>
                <TableHead>说明</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {revisions.map((revision) => (
                <TableRow key={revision}>
                  <TableCell className='font-mono text-xs'>rev {revision}</TableCell>
                  <TableCell>
                    {revision === profile.revision ? (
                      <DigestTag value={profile.digest} />
                    ) : (
                      <span className='text-muted-foreground text-xs'>
                        不可变历史版本（Digest 略）
                      </span>
                    )}
                  </TableCell>
                  <TableCell className='text-muted-foreground text-sm'>
                    {revision === profile.revision ? '当前版本' : 'Profile 发布后版本不可变，回滚即指向旧 Digest'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className='text-muted-foreground text-xs'>
          Frontend Profile 每次发布生成新的不可变 Revision + Digest；修订只能追加新版本，不能改写历史。
        </p>
      </TabsContent>

      <TabsContent value='conformance'>
        <ProfileConformanceTab runs={conformanceRuns} />
      </TabsContent>
      <TabsContent value='audit'>
        <ProfileAuditTab entries={audits} />
      </TabsContent>
    </Tabs>
  );
}
