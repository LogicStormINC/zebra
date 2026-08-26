'use client';

import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Icons } from '@/components/icons';
import type { OnboardingFrontend } from '../lib/onboarding-state';
import { FormRow, MultiValueInput } from './onboarding-fields';

const HOOK_SAMPLE = `// Host 前端挂载 Zebra 能力（PRD 14.5 React Hook 契约）
import { useZebraReadable, useZebraAction } from '@zebra/frontend-sdk';

// 订阅平台下发的 Readable（自动对齐 uiRevision）
const route = useZebraReadable('page.route', { strategy: 'on_change' });

// 声明 Action（receipt_required：执行后必须回执）
const [highlight, { pending }] = useZebraAction('ui.highlight_ticket', {
  executionMode: 'receipt_required'
});`;

/** Step 5 Frontend Capability Profile（PRD 14）：profile 概要 + Hook 示例。 */
export function OnboardingStepFrontend({
  value,
  onChange
}: {
  value: OnboardingFrontend;
  onChange: (next: OnboardingFrontend) => void;
}) {
  const numberField = (raw: string, fallback: number) => {
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };

  return (
    <div className='flex flex-col gap-4'>
      <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
        <FormRow label='Frontend App ID' required hint='前端应用标识，与 Host App 关联'>
          <Input
            value={value.frontendAppId}
            placeholder='trench-web'
            className='font-mono'
            onChange={(event) => onChange({ ...value, frontendAppId: event.target.value })}
          />
        </FormRow>
        <FormRow label='Profile Revision' hint='Frontend Profile 版本号，发布后单调递增'>
          <Input
            type='number'
            min={1}
            value={value.profileRevision}
            onChange={(event) => onChange({ ...value, profileRevision: numberField(event.target.value, 1) })}
          />
        </FormRow>
        <FormRow label='Build ID' hint='与 CI 构建产物对应的构建标识'>
          <Input
            value={value.buildId}
            placeholder='build-2026.08.25-01'
            className='font-mono'
            onChange={(event) => onChange({ ...value, buildId: event.target.value })}
          />
        </FormRow>
        <FormRow label='Allowed Origins' hint='前端运行来源白名单，与 Inbound Trust 联合校验'>
          <MultiValueInput
            values={value.allowedOrigins}
            onChange={(allowedOrigins) => onChange({ ...value, allowedOrigins })}
            placeholder='https://app.example.com'
          />
        </FormRow>
        <FormRow label='Readables 数量' hint='本次接入计划挂载的 Readable 契约数'>
          <Input
            type='number'
            min={0}
            value={value.readableCount}
            onChange={(event) => onChange({ ...value, readableCount: numberField(event.target.value, 0) })}
          />
        </FormRow>
        <FormRow label='Actions 数量' hint='本次接入计划挂载的 Action 契约数'>
          <Input
            type='number'
            min={0}
            value={value.actionCount}
            onChange={(event) => onChange({ ...value, actionCount: numberField(event.target.value, 0) })}
          />
        </FormRow>
      </div>

      <Card className='py-0'>
        <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
          <CardTitle className='flex items-center gap-2 text-sm'>
            <Icons.hook className='size-4' />
            React Hook 接入示例
          </CardTitle>
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={() => toast.success('Runtime Mount 检查已执行（演示）')}
          >
            Runtime Mount 检查
          </Button>
        </CardHeader>
        <CardContent className='p-0'>
          <pre className='overflow-auto bg-muted/40 rounded-b-lg p-3 font-mono text-xs leading-relaxed'>
            {HOOK_SAMPLE}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
