'use client';

import { useState } from 'react';

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { EmptyState } from '@/components/platform/empty-state';
import type { FrontendProfile } from '@/lib/platform/types';
import { HookCodePanel } from './hook-code-panel';

/**
 * Hook Contract 页（PRD 13.7）：顶部选择 Frontend Profile，
 * 下方渲染按该 Profile 生成的 Hook 接入代码。
 */
export function HooksContractView({ profiles }: { profiles: FrontendProfile[] }) {
  const [profileId, setProfileId] = useState(profiles[0]?.id ?? '');
  const selected = profiles.find((profile) => profile.id === profileId) ?? profiles[0];

  if (!selected) {
    return (
      <EmptyState
        title='暂无 Frontend Profile'
        description='先在接入向导中创建 Frontend Profile，再生成 Hook 接入代码'
        icon='hook'
      />
    );
  }

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-sm font-medium'>Frontend Profile</span>
        <Select value={selected.id} onValueChange={(value) => value && setProfileId(value)}>
          <SelectTrigger className='w-80' aria-label='选择 Frontend Profile'>
            <SelectValue placeholder='选择 Frontend Profile' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {profiles.map((profile) => (
                <SelectItem key={profile.id} value={profile.id}>
                  {profile.frontendAppId}（{profile.hostAppId} · rev {profile.revision}）
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <HookCodePanel profile={selected} />
    </div>
  );
}
