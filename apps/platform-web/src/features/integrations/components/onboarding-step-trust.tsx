'use client';

import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Icons } from '@/components/icons';
import type { OnboardingTrust } from '../lib/onboarding-state';
import { NAMESPACE_STRATEGY_LABELS } from '../lib/labels';
import { FormRow, MultiValueInput } from './onboarding-fields';

const ALGORITHM_OPTIONS = ['RS256', 'RS384', 'ES256', 'ES384', 'EdDSA'];

const TEST_ACTIONS = [
  'Test JWKS',
  'Verify Sample Grant',
  'Preview Parsed Claims',
  'Check Origin',
  'Check Clock Skew'
] as const;

/** Step 2 入站信任（PRD 13）：Issuer/Audience/JWKS 配置 + 演示性测试。 */
export function OnboardingStepTrust({
  value,
  onChange
}: {
  value: OnboardingTrust;
  onChange: (next: OnboardingTrust) => void;
}) {
  const runTest = (name: string) =>
    toast.success(`${name} 已执行（演示）`, { description: '校验结果不会写回平台数据' });

  return (
    <div className='flex flex-col gap-4'>
      <Alert>
        <Icons.lock />
        <AlertTitle>平台不展示完整 Token</AlertTitle>
        <AlertDescription>
          所有验证只返回解析结论与 Claim 摘要；完整 Token 内容不会出现在控制台、日志或审计记录中。
        </AlertDescription>
      </Alert>

      <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
        <FormRow label='Issuer' required hint='Host IdP 的签发者标识（HTTPS URL）'>
          <Input
            value={value.issuer}
            placeholder='https://auth.example.com/realms/host'
            className='font-mono'
            onChange={(event) => onChange({ ...value, issuer: event.target.value })}
          />
        </FormRow>
        <FormRow label='Audience' required hint='平台为该 Host 分配的受众标识'>
          <Input
            value={value.audience}
            className='font-mono'
            onChange={(event) => onChange({ ...value, audience: event.target.value })}
          />
        </FormRow>
        <FormRow label='JWKS URI' required hint='平台定期拉取公钥集合用于验签'>
          <Input
            value={value.jwksUri}
            placeholder='https://auth.example.com/.well-known/jwks.json'
            className='font-mono'
            onChange={(event) => onChange({ ...value, jwksUri: event.target.value })}
          />
        </FormRow>
        <FormRow label='Policy Version' hint='平台信任策略版本，随平台升级滚动'>
          <Input
            value={value.policyVersion}
            className='font-mono'
            onChange={(event) => onChange({ ...value, policyVersion: event.target.value })}
          />
        </FormRow>
        <FormRow label='Allowed Origins' hint='Client Session 建连时校验的来源白名单'>
          <MultiValueInput
            values={value.allowedOrigins}
            onChange={(allowedOrigins) => onChange({ ...value, allowedOrigins })}
            placeholder='https://app.example.com'
          />
        </FormRow>
        <FormRow label='Namespace Strategy' hint='fixed：固定命名空间；claim-mapped：按 Claim 映射'>
          <Select
            value={value.namespaceStrategy}
            onValueChange={(next) =>
              onChange({ ...value, namespaceStrategy: (next ?? 'fixed') as OnboardingTrust['namespaceStrategy'] })
            }
          >
            <SelectTrigger className='w-full'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {(['fixed', 'claim-mapped'] as const).map((strategy) => (
                  <SelectItem key={strategy} value={strategy}>
                    {NAMESPACE_STRATEGY_LABELS[strategy]}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormRow>
        <div className='md:col-span-2'>
          <FormRow label='Algorithms' hint='允许的签名算法（建议仅保留 RS256 / ES256）'>
            <MultiValueInput
              values={value.algorithms}
              onChange={(algorithms) => onChange({ ...value, algorithms })}
              placeholder='RS256'
            />
          </FormRow>
          <div className='mt-1.5 flex flex-wrap gap-1.5'>
            {ALGORITHM_OPTIONS.filter((algo) => !value.algorithms.includes(algo)).map((algo) => (
              <Button
                key={algo}
                type='button'
                variant='outline'
                size='xs'
                className='font-mono'
                onClick={() => onChange({ ...value, algorithms: [...value.algorithms, algo] })}
              >
                + {algo}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <div className='flex flex-wrap items-center gap-2 border-t pt-4'>
        {TEST_ACTIONS.map((action) => (
          <Button key={action} type='button' variant='outline' size='sm' onClick={() => runTest(action)}>
            {action}
          </Button>
        ))}
      </div>
    </div>
  );
}
