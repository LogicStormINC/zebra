'use client';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DigestTag } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime, relativeTime } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import type { DefinitionDetailData } from './definition-detail-data';
import { DefinitionOverviewTab } from './definition-overview-tab';
import {
  DefinitionDraftTab,
  DefinitionReleaseTab,
  DefinitionVersionsTab
} from './definition-lifecycle-tabs';
import {
  DefinitionCapabilitiesTab,
  DefinitionMemoryPolicyTab,
  DefinitionModelPolicyTab,
  DefinitionRuntimePolicyTab,
  DefinitionToolPolicyTab
} from './definition-profile-tabs';
import {
  DefinitionAuditTab,
  DefinitionBindingsTab,
  DefinitionEvaluationTab
} from './definition-relation-tabs';

const LIFECYCLE_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

/** Definition 详情（PRD 14.2）：12 个 Tab 的完整视图。 */
export function DefinitionDetail({ data }: { data: DefinitionDetailData }) {
  const { definition, publishedRelease } = data;

  return (
    <div className='flex flex-col gap-4 p-4 md:px-6'>
      {publishedRelease && (
        <Card className='py-0'>
          <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
            <CardTitle className='flex items-center gap-2 text-sm'>
              <Icons.agentRelease className='size-4' />
              Published Release：{publishedRelease.id}
            </CardTitle>
            <StatusBadge tone={lifecycleTone(publishedRelease.status)}>
              {LIFECYCLE_LABELS[publishedRelease.status] ?? publishedRelease.status}
            </StatusBadge>
          </CardHeader>
          <CardContent className='text-muted-foreground flex flex-wrap items-center gap-x-6 gap-y-1.5 p-4 text-xs'>
            <span>
              Channel <span className='text-foreground font-medium'>{publishedRelease.channel}</span>
            </span>
            <span>
              Version <span className='text-foreground font-medium tabular-nums'>v{publishedRelease.version}</span>
            </span>
            <span className='flex items-center gap-1.5'>
              Digest <DigestTag value={publishedRelease.digest} />
            </span>
            <span>
              Bound Hosts <span className='text-foreground font-medium tabular-nums'>{publishedRelease.boundHosts}</span>
            </span>
            <span>
              Released <span className='text-foreground font-medium'>{formatDateTime(publishedRelease.releasedAt)}</span>
            </span>
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue='overview'>
        <div className='overflow-x-auto pb-1'>
          <TabsList className='h-auto flex-nowrap'>
            <TabsTrigger value='overview'>Overview</TabsTrigger>
            <TabsTrigger value='draft'>Draft</TabsTrigger>
            <TabsTrigger value='versions'>Versions</TabsTrigger>
            <TabsTrigger value='release'>Release</TabsTrigger>
            <TabsTrigger value='capabilities'>Capabilities</TabsTrigger>
            <TabsTrigger value='model-policy'>Model Policy</TabsTrigger>
            <TabsTrigger value='tool-policy'>Tool Policy</TabsTrigger>
            <TabsTrigger value='memory-policy'>Memory Policy</TabsTrigger>
            <TabsTrigger value='runtime-policy'>Runtime Policy</TabsTrigger>
            <TabsTrigger value='evaluation'>Evaluation</TabsTrigger>
            <TabsTrigger value='host-bindings'>Host Bindings</TabsTrigger>
            <TabsTrigger value='audit'>Audit</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value='overview' className='mt-4'>
          <DefinitionOverviewTab data={data} />
        </TabsContent>
        <TabsContent value='draft' className='mt-4'>
          <DefinitionDraftTab data={data} />
        </TabsContent>
        <TabsContent value='versions' className='mt-4'>
          <DefinitionVersionsTab data={data} />
        </TabsContent>
        <TabsContent value='release' className='mt-4'>
          <DefinitionReleaseTab data={data} />
        </TabsContent>
        <TabsContent value='capabilities' className='mt-4'>
          <DefinitionCapabilitiesTab data={data} />
        </TabsContent>
        <TabsContent value='model-policy' className='mt-4'>
          <DefinitionModelPolicyTab data={data} />
        </TabsContent>
        <TabsContent value='tool-policy' className='mt-4'>
          <DefinitionToolPolicyTab data={data} />
        </TabsContent>
        <TabsContent value='memory-policy' className='mt-4'>
          <DefinitionMemoryPolicyTab data={data} />
        </TabsContent>
        <TabsContent value='runtime-policy' className='mt-4'>
          <DefinitionRuntimePolicyTab data={data} />
        </TabsContent>
        <TabsContent value='evaluation' className='mt-4'>
          <DefinitionEvaluationTab data={data} />
        </TabsContent>
        <TabsContent value='host-bindings' className='mt-4'>
          <DefinitionBindingsTab data={data} />
        </TabsContent>
        <TabsContent value='audit' className='mt-4'>
          <DefinitionAuditTab data={data} />
        </TabsContent>
      </Tabs>

      <p className='text-muted-foreground text-xs'>
        Definition 最后更新：{formatDateTime(definition.updatedAt)}（{relativeTime(definition.updatedAt)}）
      </p>
    </div>
  );
}
