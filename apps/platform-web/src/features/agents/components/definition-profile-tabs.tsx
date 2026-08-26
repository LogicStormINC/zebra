'use client';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataList } from '@/components/platform/data-list';
import { EmptyState } from '@/components/platform/empty-state';
import { DigestTag, MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import type { PolicyRecord } from '@/lib/platform/types';
import type { DefinitionDetailData } from './definition-detail-data';

/** Capabilities Tab：capabilityCeiling + toolProfile 的三组能力列表。 */
export function DefinitionCapabilitiesTab({ data }: { data: DefinitionDetailData }) {
  const { definition, capabilityProfile } = data;
  return (
    <div className='flex flex-col gap-4'>
      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Capability Ceiling（能力上限）</CardTitle>
        </CardHeader>
        <CardContent className='p-4'>
          <div className='flex flex-wrap gap-1.5'>
            {definition.capabilityCeiling.map((capability) => (
              <Badge key={capability} variant='secondary' className='font-mono text-xs'>
                {capability}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      {capabilityProfile ? (
        <Card className='py-0'>
          <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
            <CardTitle className='flex items-center gap-2 text-sm'>
              Tool Profile：{capabilityProfile.name}
            </CardTitle>
            <span className='text-muted-foreground flex items-center gap-2 text-xs'>
              rev {capabilityProfile.revision} <DigestTag value={capabilityProfile.digest} />
            </span>
          </CardHeader>
          <CardContent className='flex flex-col gap-4 p-4'>
            <CapabilityGroup
              title='Backend Tools（后端工具）'
              items={capabilityProfile.backendTools}
              emptyText='无后端工具'
            />
            <CapabilityGroup
              title='Client Actions（前端动作）'
              items={capabilityProfile.clientActions}
              emptyText='无前端动作'
            />
            <CapabilityGroup
              title='Readables（可读上下文）'
              items={capabilityProfile.readables}
              emptyText='无可读上下文'
            />
          </CardContent>
        </Card>
      ) : (
        <EmptyState
          icon='agent'
          title='未找到 Tool Profile'
          description={`Capability Profile ${definition.toolProfileId} 不存在或已被删除`}
        />
      )}
    </div>
  );
}

function CapabilityGroup({ title, items, emptyText }: { title: string; items: string[]; emptyText: string }) {
  return (
    <div>
      <p className='text-muted-foreground mb-1.5 text-xs font-medium'>{title}</p>
      {items.length === 0 ? (
        <p className='text-muted-foreground text-sm'>{emptyText}</p>
      ) : (
        <div className='flex flex-wrap gap-1.5'>
          {items.map((item) => (
            <Badge key={item} variant='outline' className='font-mono text-xs'>
              {item}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

const POLICY_KIND_LABELS: Record<string, string> = {
  model: 'Model Policy（模型策略）',
  tool: 'Tool Policy（工具策略）',
  memory: 'Memory Policy（记忆策略）',
  runtime: 'Runtime Policy（运行时策略）'
};

function PolicyTab({ policy, fallbackId, kind }: { policy?: PolicyRecord; fallbackId: string; kind: keyof typeof POLICY_KIND_LABELS }) {
  if (!policy) {
    return (
      <EmptyState
        icon='policy'
        title={`该 Definition 未配置${POLICY_KIND_LABELS[kind]}`}
        description={`解析引用 ${fallbackId} 未找到已发布的 PolicyRecord`}
      />
    );
  }
  return (
    <Card className='py-0'>
      <CardHeader className='border-b px-4 py-3'>
        <CardTitle className='flex items-center gap-2 text-sm'>
          {POLICY_KIND_LABELS[kind]}
          <StatusBadge tone={lifecycleTone(policy.status)}>{policy.status}</StatusBadge>
        </CardTitle>
      </CardHeader>
      <CardContent className='flex flex-col gap-4 p-4'>
        <DataList
          columns={2}
          items={[
            { label: 'Policy ID', value: <MonoId value={policy.id} copyable={false} /> },
            { label: 'Name', value: policy.name },
            { label: 'Level', value: <Badge variant='outline'>{policy.level}</Badge> },
            { label: 'Scope', value: policy.scope },
            { label: 'Revision', value: `rev ${policy.revision}` },
            { label: 'Digest', value: <DigestTag value={policy.digest} /> },
            { label: 'Updated By', value: policy.updatedBy },
            { label: 'Updated At', value: formatDateTime(policy.updatedAt) }
          ]}
        />
        <div>
          <Button variant='link' className='h-auto p-0 text-sm' render={<Link href='/governance/policies' aria-label='在治理中心查看策略' />}>
            在治理中心查看 /governance/policies
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** Model / Tool / Memory / Runtime Policy Tabs。 */
export function DefinitionModelPolicyTab({ data }: { data: DefinitionDetailData }) {
  return (
    <PolicyTab
      policy={data.modelPolicy}
      fallbackId={data.definition.modelPolicyId}
      kind='model'
    />
  );
}

export function DefinitionToolPolicyTab({ data }: { data: DefinitionDetailData }) {
  return <PolicyTab policy={data.toolPolicy} fallbackId='kind=tool' kind='tool' />;
}

export function DefinitionMemoryPolicyTab({ data }: { data: DefinitionDetailData }) {
  return (
    <PolicyTab
      policy={data.memoryPolicy}
      fallbackId={data.definition.memoryPolicyId ?? '（未配置）'}
      kind='memory'
    />
  );
}

export function DefinitionRuntimePolicyTab({ data }: { data: DefinitionDetailData }) {
  return (
    <PolicyTab
      policy={data.runtimePolicy}
      fallbackId={data.definition.runtimeProfileId}
      kind='runtime'
    />
  );
}
