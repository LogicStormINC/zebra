'use client';

import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Icons } from '@/components/icons';
import type { OnboardingConnector } from '../lib/onboarding-state';
import { FormRow, MultiValueInput } from './onboarding-fields';

const CHECK_ACTIONS = [
  'Endpoint Health Check',
  'TLS Check',
  'Manifest Fetch',
  'Credential Ref Check',
  'Network Policy Check'
] as const;

const numberField = (raw: string, fallback: number) => {
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

/** Step 3 出站 Connector（PRD 11）：端点与引用登记；凭据仅存引用不存明文。 */
export function OnboardingStepConnector({
  value,
  onChange
}: {
  value: OnboardingConnector;
  onChange: (next: OnboardingConnector) => void;
}) {
  const runCheck = (name: string) =>
    toast.success(`${name} 已执行（演示）`, { description: '检查结果不会写回平台数据' });

  return (
    <div className='flex flex-col gap-4'>
      <Alert>
        <Icons.credential />
        <AlertTitle>Credential 仅保存引用</AlertTitle>
        <AlertDescription>
          平台只保存 Credential Ref（如 vault://…）并在运行时通过 Credential Provider 换取短期凭据，
          不落任何明文（PRD 6.5）。
        </AlertDescription>
      </Alert>

      <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
        <FormRow label='Connector ID' required hint='Host 侧 Connector 的稳定标识'>
          <Input
            value={value.connectorId}
            placeholder='conn_example_01'
            className='font-mono'
            onChange={(event) => onChange({ ...value, connectorId: event.target.value })}
          />
        </FormRow>
        <FormRow label='Base URI' required hint='Connector 服务根地址（HTTPS）'>
          <Input
            value={value.baseUri}
            placeholder='https://connector.example.com'
            className='font-mono'
            onChange={(event) => onChange({ ...value, baseUri: event.target.value })}
          />
        </FormRow>
        <FormRow label='Manifest Path' hint='拉取后端能力清单的路径'>
          <Input
            value={value.manifestPath}
            className='font-mono'
            onChange={(event) => onChange({ ...value, manifestPath: event.target.value })}
          />
        </FormRow>
        <FormRow label='Invoke Path' hint='工具调用端点'>
          <Input
            value={value.invokePath}
            className='font-mono'
            onChange={(event) => onChange({ ...value, invokePath: event.target.value })}
          />
        </FormRow>
        <FormRow label='Reconcile Path' hint='Effect 对账端点（write tool 必需）'>
          <Input
            value={value.reconcilePath}
            className='font-mono'
            onChange={(event) => onChange({ ...value, reconcilePath: event.target.value })}
          />
        </FormRow>
        <FormRow label='Workload Identity Ref' hint='Connector 出站调用使用的工作负载身份'>
          <Input
            value={value.workloadIdentityRef}
            placeholder='workload:connector@prod'
            className='font-mono'
            onChange={(event) => onChange({ ...value, workloadIdentityRef: event.target.value })}
          />
        </FormRow>
        <FormRow label='Credential Ref' hint='仅保存引用，不保存明文凭据'>
          <Input
            value={value.credentialRef}
            placeholder='vault://host/connector-workload'
            className='font-mono'
            onChange={(event) => onChange({ ...value, credentialRef: event.target.value })}
          />
        </FormRow>
        <FormRow label='Network Policy Ref' hint='出站网络策略引用（egress 白名单）'>
          <Input
            value={value.networkPolicyRef}
            placeholder='netpol/egress-connector'
            className='font-mono'
            onChange={(event) => onChange({ ...value, networkPolicyRef: event.target.value })}
          />
        </FormRow>
        <FormRow label='Protocol Versions' hint='支持的 zebra-connector 协议版本'>
          <MultiValueInput
            values={value.protocolVersions}
            onChange={(protocolVersions) => onChange({ ...value, protocolVersions })}
            placeholder='zebra-connector/1.2'
          />
        </FormRow>
        <div className='grid grid-cols-3 gap-3'>
          <FormRow label='连接超时(s)'>
            <Input
              type='number'
              min={1}
              value={value.connectTimeoutSeconds}
              onChange={(event) =>
                onChange({ ...value, connectTimeoutSeconds: numberField(event.target.value, 5) })
              }
            />
          </FormRow>
          <FormRow label='读取超时(s)'>
            <Input
              type='number'
              min={1}
              value={value.readTimeoutSeconds}
              onChange={(event) =>
                onChange({ ...value, readTimeoutSeconds: numberField(event.target.value, 30) })
              }
            />
          </FormRow>
          <FormRow label='最大重试'>
            <Input
              type='number'
              min={0}
              value={value.maxRetries}
              onChange={(event) => onChange({ ...value, maxRetries: numberField(event.target.value, 3) })}
            />
          </FormRow>
        </div>
      </div>

      <div className='flex flex-wrap items-center gap-2 border-t pt-4'>
        {CHECK_ACTIONS.map((action) => (
          <Button key={action} type='button' variant='outline' size='sm' onClick={() => runCheck(action)}>
            {action}
          </Button>
        ))}
      </div>
    </div>
  );
}
