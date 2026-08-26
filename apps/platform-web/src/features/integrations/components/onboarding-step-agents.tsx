'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Icons } from '@/components/icons';
import { EmptyState } from '@/components/platform/empty-state';
import type { OnboardingAgents } from '../lib/onboarding-state';
import { FormRow } from './onboarding-fields';

export type AgentOption = { id: string; label: string; channel?: string };

/** 「跟随平台默认」选项值：草稿中映射回空字符串（不绑定具体 Policy）。 */
const FOLLOW_PLATFORM_DEFAULT = 'follow-platform-default';

const toSelectValue = (policyId: string) => policyId || FOLLOW_PLATFORM_DEFAULT;

const fromSelectValue = (next: string) => (next === FOLLOW_PLATFORM_DEFAULT ? '' : next);

/** Step 6 Agent 与策略（PRD 10.3）：选择 Release / Capability / Policy / Quota 并预览有效能力。 */
export function OnboardingStepAgents({
  value,
  onChange,
  agentReleases,
  capabilityProfiles,
  policies,
  quotas,
  capabilityCeilings,
  modelPolicies,
  runtimePolicies,
  approvalPolicies
}: {
  value: OnboardingAgents;
  onChange: (next: OnboardingAgents) => void;
  agentReleases: AgentOption[];
  capabilityProfiles: AgentOption[];
  policies: AgentOption[];
  quotas: AgentOption[];
  /** definitionId → capabilityCeiling */
  capabilityCeilings: Record<string, string[]>;
  modelPolicies: AgentOption[];
  runtimePolicies: AgentOption[];
  approvalPolicies: AgentOption[];
}) {
  const selectedRelease = agentReleases.find((release) => release.id === value.agentReleaseId);
  const ceiling = selectedRelease ? (capabilityCeilings[selectedRelease.id] ?? []) : [];

  if (agentReleases.length === 0) {
    return (
      <EmptyState
        title='暂无可选 Agent Release'
        description='请先在 Agent 资产中发布至少一个 Release，再回到向导完成绑定'
        icon='agentRelease'
      />
    );
  }

  return (
    <div className='flex flex-col gap-4'>
      <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
        <FormRow label='Agent Release' required hint='该 Host 默认绑定的 Agent Release'>
          <Select
            value={value.agentReleaseId}
            onValueChange={(next) => onChange({ ...value, agentReleaseId: next ?? '' })}
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
        </FormRow>
        <FormRow label='Capability Profile' hint='限定的后端工具与前端动作集合'>
          <Select
            value={value.capabilityProfileId}
            onValueChange={(next) => onChange({ ...value, capabilityProfileId: next ?? '' })}
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder='选择 Capability Profile' />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {capabilityProfiles.map((profile) => (
                  <SelectItem key={profile.id} value={profile.id}>
                    {profile.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormRow>
        <FormRow label='Policy' hint='默认应用的 Policy 组合（model / tool / runtime）'>
          <Select
            value={value.policyId}
            onValueChange={(next) => onChange({ ...value, policyId: next ?? '' })}
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder='选择 Policy' />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {policies.map((policy) => (
                  <SelectItem key={policy.id} value={policy.id}>
                    {policy.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormRow>
        <FormRow label='Model Policy' hint='模型路由与 Token 上限；不选则跟随平台默认'>
          <Select
            value={toSelectValue(value.modelPolicyId)}
            onValueChange={(next) =>
              onChange({ ...value, modelPolicyId: fromSelectValue(next ?? '') })
            }
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder='跟随平台默认' />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value={FOLLOW_PLATFORM_DEFAULT}>跟随平台默认</SelectItem>
                {modelPolicies.map((policy) => (
                  <SelectItem key={policy.id} value={policy.id}>
                    {policy.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormRow>
        <FormRow label='Runtime Policy' hint='沙箱与运行时约束；不选则跟随平台默认'>
          <Select
            value={toSelectValue(value.runtimePolicyId)}
            onValueChange={(next) =>
              onChange({ ...value, runtimePolicyId: fromSelectValue(next ?? '') })
            }
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder='跟随平台默认' />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value={FOLLOW_PLATFORM_DEFAULT}>跟随平台默认</SelectItem>
                {runtimePolicies.map((policy) => (
                  <SelectItem key={policy.id} value={policy.id}>
                    {policy.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormRow>
        <FormRow label='Approval Policy' hint='高风险操作的审批要求；不选则跟随平台默认'>
          <Select
            value={toSelectValue(value.approvalPolicyId)}
            onValueChange={(next) =>
              onChange({ ...value, approvalPolicyId: fromSelectValue(next ?? '') })
            }
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder='跟随平台默认' />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value={FOLLOW_PLATFORM_DEFAULT}>跟随平台默认</SelectItem>
                {approvalPolicies.map((policy) => (
                  <SelectItem key={policy.id} value={policy.id}>
                    {policy.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormRow>
        <FormRow label='Quota' hint='该 Host 的并发 / Token / 成本配额'>
          <Select
            value={value.quotaId}
            onValueChange={(next) => onChange({ ...value, quotaId: next ?? '' })}
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder='选择 Quota' />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {quotas.map((quota) => (
                  <SelectItem key={quota.id} value={quota.id}>
                    {quota.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormRow>
      </div>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='flex items-center gap-2 text-sm'>
            <Icons.exclusive className='size-4' />
            Effective Capability Preview
          </CardTitle>
        </CardHeader>
        <CardContent className='p-4'>
          {!selectedRelease ? (
            <p className='text-muted-foreground text-sm'>
              选择 Agent Release 后展示其 capabilityCeiling。
            </p>
          ) : ceiling.length === 0 ? (
            <p className='text-muted-foreground text-sm'>
              {selectedRelease.label} 未声明 capabilityCeiling。
            </p>
          ) : (
            <div className='space-y-2'>
              <p className='text-muted-foreground text-xs'>
                {selectedRelease.label} 的 capabilityCeiling（Agent
                可请求的能力上限，实际可用集合还需与 Capability Profile / Policy 求交集）：
              </p>
              <div className='flex flex-wrap gap-1.5'>
                {ceiling.map((capability) => (
                  <Badge key={capability} variant='secondary' className='font-mono'>
                    {capability}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
