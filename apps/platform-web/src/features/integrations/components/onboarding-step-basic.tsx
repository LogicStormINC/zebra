'use client';

import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import type { Environment } from '@/lib/platform/types';
import type { OnboardingBasic } from '../lib/onboarding-state';
import { ENVIRONMENT_LABELS } from '../lib/labels';
import { FormRow, MultiValueInput } from './onboarding-fields';

const ENVIRONMENTS: Environment[] = ['development', 'staging', 'production'];

/** Step 1 基础信息（PRD 10.3）：Name/App ID 发布后不可变。 */
export function OnboardingStepBasic({
  value,
  onChange
}: {
  value: OnboardingBasic;
  onChange: (next: OnboardingBasic) => void;
}) {
  return (
    <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
      <FormRow label='Host Name' required hint="业务 Host 的展示名称，例如 'Trench 交易平台'">
        <Input
          value={value.name}
          placeholder='输入 Host 名称'
          onChange={(event) => onChange({ ...value, name: event.target.value })}
        />
      </FormRow>
      <FormRow label='Host App ID' required hint='发布后不可修改，将作为 Namespace 与授权的固定主体'>
        <Input
          value={value.appId}
          placeholder='例如 trench'
          className='font-mono'
          onChange={(event) => onChange({ ...value, appId: event.target.value })}
        />
      </FormRow>
      <FormRow label='Owner Team' hint='负责该 Host 接入与运营的团队'>
        <Input
          value={value.ownerTeam}
          placeholder='例如 platform-team'
          onChange={(event) => onChange({ ...value, ownerTeam: event.target.value })}
        />
      </FormRow>
      <FormRow label='Environment' hint='接入目标环境，决定默认的 Policy 与 Quota 集合'>
        <Select
          value={value.environment}
          onValueChange={(next) => onChange({ ...value, environment: (next ?? 'staging') as Environment })}
        >
          <SelectTrigger className='w-full'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {ENVIRONMENTS.map((env) => (
                <SelectItem key={env} value={env}>
                  {ENVIRONMENT_LABELS[env]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </FormRow>
      <FormRow label='Contact' hint='接入告警与审批通知的联系人（邮箱或 IM）'>
        <Input
          value={value.contact}
          placeholder='owners@example.com'
          onChange={(event) => onChange({ ...value, contact: event.target.value })}
        />
      </FormRow>
      <FormRow label='Tags' hint='用于筛选与审计归组'>
        <MultiValueInput values={value.tags} onChange={(tags) => onChange({ ...value, tags })} />
      </FormRow>
      <div className='md:col-span-2'>
        <FormRow label='Description' hint='一句话说明该 Host 的业务用途'>
          <Textarea
            value={value.description}
            placeholder='例如：交易风险分析与工程助手试点'
            rows={3}
            onChange={(event) => onChange({ ...value, description: event.target.value })}
          />
        </FormRow>
      </div>
    </div>
  );
}
