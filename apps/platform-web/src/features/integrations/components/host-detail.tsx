'use client';

import Link from 'next/link';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Icons } from '@/components/icons';
import { DataList } from '@/components/platform/data-list';
import { MonoId } from '@/components/platform/mono-id';
import { PageHeader } from '@/components/platform/page-header';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime, formatNumber } from '@/lib/platform/format';
import type {
  AuditEntry,
  BackendManifest,
  ClientSession,
  ConformanceRun,
  Connector,
  FrontendProfile,
  Host,
  InboundTrust,
  NamespaceBinding,
  Task,
  UsageRecord
} from '@/lib/platform/types';
import {
  CONFORMANCE_LABELS,
  ENVIRONMENT_LABELS,
  HOST_STATUS_LABELS,
  hostStatusTone
} from '../lib/labels';
import {
  HostAgentBindingsTab,
  HostAuditTab,
  HostBindingsTab,
  HostConformanceTab,
  HostUsageTab
} from './host-governance-tabs';
import { HostOverviewTab } from './host-overview-tab';
import {
  HostBackendTab,
  HostConnectorTab,
  HostFrontendTab,
  HostTrustTab
} from './host-resource-tabs';

/** Host 详情页（PRD 10.2）：页头 + 十个信息 Tab。 */
export function HostDetail({
  host,
  trust,
  connector,
  manifest,
  frontendProfile,
  bindings,
  conformanceRuns,
  auditEntries,
  tasks,
  clientSessions,
  usage,
  releaseNames
}: {
  host: Host;
  trust?: InboundTrust;
  connector?: Connector;
  manifest?: BackendManifest;
  frontendProfile?: FrontendProfile;
  bindings: NamespaceBinding[];
  conformanceRuns: ConformanceRun[];
  auditEntries: AuditEntry[];
  tasks: Task[];
  clientSessions: ClientSession[];
  usage: UsageRecord[];
  releaseNames: Record<string, string>;
}) {
  const runConformance = () =>
    toast.success('Conformance Run 已触发（演示）', {
      description: `${host.appId} · backend + frontend surface`
    });

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title={
          <span className='flex flex-wrap items-center gap-2'>
            {host.name}
            <MonoId value={host.appId} head={8} tail={4} copyable={false} />
            <StatusBadge tone={host.environment === 'production' ? 'running' : 'draft'} withDot={false}>
              {ENVIRONMENT_LABELS[host.environment]}
            </StatusBadge>
            <StatusBadge tone={hostStatusTone(host.status)}>
              {HOST_STATUS_LABELS[host.status]}
            </StatusBadge>
          </span>
        }
        description={host.description}
        actions={
          <>
            {host.onboardingStep < 7 && (
              <Button render={<Link href='/integrations/onboarding' aria-label='继续接入' />}>
                <Icons.forms data-icon='inline-start' />
                继续接入（{host.onboardingStep}/7）
              </Button>
            )}
            <Button variant='outline' onClick={runConformance}>
              <Icons.conformance data-icon='inline-start' />
              运行 Conformance
            </Button>
            <RiskConfirmDialog
              trigger={
                <Button variant='destructive'>
                  <Icons.warning data-icon='inline-start' />
                  暂停接入
                </Button>
              }
              title='暂停 Host 接入'
              impact={`Host ${host.appId}（${host.name}）：新的 Task 将被拒绝调度，运行中 Task 继续直至完成或超时。`}
              irreversibility='可由 Operator 手动恢复；恢复后需重新执行 Conformance。'
              currentRevision={`onboarding step ${host.onboardingStep}/7`}
              actionLabel='确认暂停'
              onConfirm={(reason) =>
                toast.success('暂停请求已记录（演示）', { description: `审计原因：${reason}` })
              }
            />
            <Button variant='outline' render={<Link href='/governance/audit' aria-label='查看审计' />}>
              查看审计
            </Button>
          </>
        }
        meta={
          <DataList
            columns={3}
            className='grid-cols-1 gap-x-6 sm:grid-cols-3 md:grid-cols-3 w-full'
            items={[
              { label: 'Owner', value: host.owner },
              { label: 'Contact', value: host.contact },
              { label: 'Agent Releases', value: `${host.agentReleaseCount} 个` },
              {
                label: '当前 Connector Rev',
                value: host.connectorRevision ? `conn rev ${host.connectorRevision}` : '—'
              },
              {
                label: 'Backend Manifest Rev',
                value: host.manifestRevision ? `rev ${host.manifestRevision}` : '—'
              },
              {
                label: 'Frontend Profile Rev',
                value: host.frontendProfileRevision ? `rev ${host.frontendProfileRevision}` : '—'
              },
              { label: 'Last Conformance', value: CONFORMANCE_LABELS[host.lastConformance] },
              {
                label: '24h Tasks',
                value: `${formatNumber(tasks.length)} 个`
              },
              { label: 'Updated At', value: formatDateTime(host.updatedAt) }
            ]}
          />
        }
      />

      <div className='flex flex-1 flex-col gap-4 p-4 md:px-6'>
        <Tabs defaultValue='overview' className='w-full'>
          <TabsList className='flex h-auto w-full flex-wrap'>
            <TabsTrigger value='overview'>Overview</TabsTrigger>
            <TabsTrigger value='trust'>Inbound Trust</TabsTrigger>
            <TabsTrigger value='connector'>Outbound Connector</TabsTrigger>
            <TabsTrigger value='backend'>Backend Capabilities</TabsTrigger>
            <TabsTrigger value='frontend'>Frontend Capabilities</TabsTrigger>
            <TabsTrigger value='bindings'>Namespace Bindings</TabsTrigger>
            <TabsTrigger value='agent-bindings'>Agent Bindings</TabsTrigger>
            <TabsTrigger value='conformance'>Conformance</TabsTrigger>
            <TabsTrigger value='usage'>Usage</TabsTrigger>
            <TabsTrigger value='audit'>Audit</TabsTrigger>
          </TabsList>

          <TabsContent value='overview' className='mt-4'>
            <HostOverviewTab
              host={host}
              trust={trust}
              connector={connector}
              frontendProfile={frontendProfile}
              tasks={tasks}
              clientSessions={clientSessions}
              recentAudit={auditEntries}
            />
          </TabsContent>
          <TabsContent value='trust' className='mt-4'>
            <HostTrustTab trust={trust} />
          </TabsContent>
          <TabsContent value='connector' className='mt-4'>
            <HostConnectorTab connector={connector} />
          </TabsContent>
          <TabsContent value='backend' className='mt-4'>
            <HostBackendTab manifest={manifest} />
          </TabsContent>
          <TabsContent value='frontend' className='mt-4'>
            <HostFrontendTab frontendProfile={frontendProfile} host={host} />
          </TabsContent>
          <TabsContent value='bindings' className='mt-4'>
            <HostBindingsTab bindings={bindings} />
          </TabsContent>
          <TabsContent value='agent-bindings' className='mt-4'>
            <HostAgentBindingsTab bindings={bindings} releaseNames={releaseNames} />
          </TabsContent>
          <TabsContent value='conformance' className='mt-4'>
            <HostConformanceTab runs={conformanceRuns} />
          </TabsContent>
          <TabsContent value='usage' className='mt-4'>
            <HostUsageTab usage={usage} />
          </TabsContent>
          <TabsContent value='audit' className='mt-4'>
            <HostAuditTab entries={auditEntries} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
