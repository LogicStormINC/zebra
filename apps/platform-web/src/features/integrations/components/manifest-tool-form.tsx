'use client';

import { useEffect, useState } from 'react';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { RiskBadge } from '@/components/platform/risk-badge';
import type { ManifestTool } from '@/lib/platform/types';
import { FormRow, MultiValueInput } from './onboarding-fields';

const RISK_OPTIONS = ['read', 'low', 'medium', 'high'] as const;
const IDEMPOTENCY_OPTIONS = ['none', 'idempotent', 'idempotency_key'] as const;
const IDEMPOTENCY_LABELS: Record<string, string> = {
  none: '不声明',
  idempotent: '天然幂等',
  idempotency_key: '幂等键'
};

/** 三栏编辑器中栏：选中 Tool 的 Contract 表单（PRD 12.4）。 */
export function ManifestToolForm({
  tool,
  capabilityVocabulary,
  onChange
}: {
  tool: ManifestTool | null;
  capabilityVocabulary: string[];
  onChange: (next: ManifestTool) => void;
}) {
  const [schemaText, setSchemaText] = useState('');
  const [schemaError, setSchemaError] = useState<string | null>(null);

  // 仅在切换选中 Tool 时重置 Schema 文本，避免编辑过程中被重新格式化打断输入
  useEffect(() => {
    setSchemaText(tool ? JSON.stringify(tool.argumentSchema, null, 2) : '');
    setSchemaError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tool 身份每次编辑都会变化，按 name 重置
  }, [tool?.name]);

  if (!tool) {
    return (
      <div className='text-muted-foreground flex flex-1 items-center justify-center p-6 text-sm'>
        在左栏选择一个 Tool 查看与编辑契约
      </div>
    );
  }

  const commitSchema = (text: string) => {
    setSchemaText(text);
    if (text.trim().length === 0) {
      setSchemaError('Schema 不能为空');
      return;
    }
    try {
      const parsed = JSON.parse(text);
      setSchemaError(null);
      onChange({ ...tool, argumentSchema: parsed as Record<string, unknown> });
    } catch (error) {
      setSchemaError(error instanceof Error ? error.message : 'JSON 解析失败');
    }
  };

  const numberValue = (raw: string, fallback: number) => {
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
  };

  return (
    <div className='flex flex-col gap-4 overflow-y-auto p-4'>
      <div className='flex items-center justify-between gap-2'>
        <p className='font-mono text-sm font-semibold'>{tool.name}</p>
        <RiskBadge risk={tool.risk} />
      </div>

      <FormRow label='Name' required>
        <Input
          value={tool.name}
          className='font-mono'
          onChange={(event) => onChange({ ...tool, name: event.target.value })}
        />
      </FormRow>

      <FormRow label='Description'>
        <Textarea
          value={tool.description}
          rows={2}
          onChange={(event) => onChange({ ...tool, description: event.target.value })}
        />
      </FormRow>

      <FormRow label='Capability' required hint='必须来自平台能力词汇表'>
        <Input
          value={tool.capability}
          className='font-mono'
          placeholder='例如 ticket:write'
          onChange={(event) => onChange({ ...tool, capability: event.target.value })}
        />
        <div className='mt-1 flex flex-wrap gap-1'>
          {capabilityVocabulary.slice(0, 8).map((capability) => (
            <button
              key={capability}
              type='button'
              className='bg-muted hover:bg-muted/70 rounded px-1.5 py-0.5 font-mono text-[10px]'
              onClick={() => onChange({ ...tool, capability })}
            >
              {capability}
            </button>
          ))}
        </div>
      </FormRow>

      <FormRow label='Required Grant Scopes' hint='调用该 Tool 需要持有的授权 Scope'>
        <MultiValueInput
          values={tool.grantScopes}
          onChange={(grantScopes) => onChange({ ...tool, grantScopes })}
          placeholder='host.resource:action'
        />
      </FormRow>

      <div className='grid grid-cols-2 gap-3'>
        <FormRow label='Risk'>
          <Select
            value={tool.risk}
            onValueChange={(next) => onChange({ ...tool, risk: (next ?? 'read') as ManifestTool['risk'] })}
          >
            <SelectTrigger className='w-full'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {RISK_OPTIONS.map((risk) => (
                  <SelectItem key={risk} value={risk}>
                    {risk}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormRow>
        <FormRow label='Idempotency'>
          <Select
            value={tool.idempotency}
            onValueChange={(next) =>
              onChange({ ...tool, idempotency: (next ?? 'none') as ManifestTool['idempotency'] })
            }
          >
            <SelectTrigger className='w-full'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {IDEMPOTENCY_OPTIONS.map((option) => (
                  <SelectItem key={option} value={option}>
                    {IDEMPOTENCY_LABELS[option]}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormRow>
      </div>

      <div className='grid grid-cols-2 gap-3'>
        <FormRow label='Timeout (s)'>
          <Input
            type='number'
            min={1}
            value={tool.timeoutSeconds}
            onChange={(event) =>
              onChange({ ...tool, timeoutSeconds: numberValue(event.target.value, tool.timeoutSeconds) })
            }
          />
        </FormRow>
        <FormRow label='Max Output Bytes'>
          <Input
            type='number'
            min={1024}
            value={tool.maxOutputBytes}
            onChange={(event) =>
              onChange({ ...tool, maxOutputBytes: numberValue(event.target.value, tool.maxOutputBytes) })
            }
          />
        </FormRow>
      </div>

      <div className='flex flex-col gap-3 rounded-lg border p-3'>
        <div className='flex items-center justify-between'>
          <Label>Parallel Safe</Label>
          <Switch
            checked={tool.parallelSafe ?? tool.risk === 'read'}
            onCheckedChange={(checked) => onChange({ ...tool, parallelSafe: checked })}
          />
        </div>
        <p className='text-muted-foreground text-xs'>允许平台并行调度多个该 Tool 调用。</p>
        <div className='flex items-center justify-between border-t pt-3'>
          <Label>Effect Reconcile Capable</Label>
          <Switch
            checked={tool.reconcileCapable}
            onCheckedChange={(checked) => onChange({ ...tool, reconcileCapable: checked })}
          />
        </div>
        <p className='text-muted-foreground text-xs'>
          写操作 Effect 可通过 Connector reconcile 端点对账（Uncertain Effect 恢复必需）。
        </p>
      </div>

      <FormRow label='Arguments Schema (JSON)' required>
        <Textarea
          value={schemaText}
          rows={10}
          className='font-mono text-xs'
          onChange={(event) => commitSchema(event.target.value)}
        />
        {schemaError && <p className='text-destructive text-xs'>{schemaError}</p>}
      </FormRow>
    </div>
  );
}
