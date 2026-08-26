'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
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
import { Textarea } from '@/components/ui/textarea';
import type { ActionContract } from '@/lib/platform/types';
import { DRAFT_TOAST_DESCRIPTION, parseList, parsePositiveInt } from './contract-form-shared';
import { EXECUTION_MODE_LABELS } from './labels';

/** Action 契约编辑表单（PRD 13.5 / 35.4.1）：字段全集，保存到 Draft。 */

const EXECUTION_MODE_OPTIONS = Object.entries(EXECUTION_MODE_LABELS) as [
  ActionContract['executionMode'],
  string
][];
const RISK_OPTIONS: [ActionContract['risk'], string][] = [
  ['presentation', 'presentation（呈现）'],
  ['navigation', 'navigation（导航）'],
  ['local_state', 'local_state（本地状态）'],
  ['user_interaction', 'user_interaction（用户交互）']
];

type ActionFormState = {
  name: string;
  description: string;
  capability: string;
  risk: ActionContract['risk'];
  executionMode: ActionContract['executionMode'];
  timeoutMs: string;
  requiresController: boolean;
  requiresUserConfirmation: boolean;
  parametersSchema: string;
  resultSchema: string;
  maxResultBytes: string;
  allowedRoutes: string;
  resourceBindings: string;
};

function actionFormFrom(initial: ActionContract | null): ActionFormState {
  return {
    name: initial?.name ?? '',
    description: initial?.description ?? '',
    capability: initial?.capability ?? 'presentation',
    risk: initial?.risk ?? 'presentation',
    executionMode: initial?.executionMode ?? 'receipt_required',
    timeoutMs: String(initial?.timeoutMs ?? 8000),
    requiresController: initial?.requiresController ?? true,
    requiresUserConfirmation: initial?.requiresUserConfirmation ?? false,
    parametersSchema: initial?.parametersSchema ?? '',
    resultSchema: initial?.resultSchema ?? '',
    maxResultBytes: String(initial?.maxResultBytes ?? 512),
    allowedRoutes: initial?.allowedRoutes?.join(', ') ?? '',
    resourceBindings: initial?.resourceBindings?.join(', ') ?? ''
  };
}

/** 前端可做的 Action 校验（PRD 13.5）：名称必填 + 两条联动规则。 */
function actionValidationError(form: ActionFormState): string | null {
  if (!form.name.trim()) return '名称必填：Action Contract 必须有唯一名称';
  if (form.executionMode === 'human_confirmed' && !form.requiresUserConfirmation) {
    return 'executionMode=human_confirmed 时必须勾选 Requires User Confirmation（确认 UI）';
  }
  if (form.risk === 'user_interaction' && !form.requiresController) {
    return 'risk=user_interaction 时必须勾选 Requires Controller（仅 Controller 会话可触发）';
  }
  return null;
}

export function ActionFormDialog({
  initial,
  profileRevision,
  onCancel,
  onSubmit
}: {
  /** null 表示新建。 */
  initial: ActionContract | null;
  profileRevision: number;
  onCancel: () => void;
  onSubmit: (contract: ActionContract) => void;
}) {
  const [form, setForm] = useState<ActionFormState>(() => actionFormFrom(initial));
  const error = actionValidationError(form);
  const set = <K extends keyof ActionFormState>(key: K, value: ActionFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const submit = () => {
    const contract: ActionContract = {
      name: form.name.trim(),
      description: form.description.trim(),
      capability: form.capability.trim() || 'presentation',
      risk: form.risk,
      executionMode: form.executionMode,
      timeoutMs: parsePositiveInt(form.timeoutMs, 8000),
      requiresController: form.requiresController,
      requiresUserConfirmation: form.requiresUserConfirmation,
      parametersSchema: form.parametersSchema.trim() || undefined,
      resultSchema: form.resultSchema.trim() || undefined,
      maxResultBytes: parsePositiveInt(form.maxResultBytes, 512),
      allowedRoutes: parseList(form.allowedRoutes),
      resourceBindings: parseList(form.resourceBindings)
    };
    onSubmit(contract);
    toast.success(`${initial ? 'Action 已保存到 Draft' : '新 Action 已保存到 Draft'}：${contract.name}`, {
      description: `${DRAFT_TOAST_DESCRIPTION}（当前 rev ${profileRevision}）`
    });
    onCancel();
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className='max-h-[85vh] max-w-2xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{initial ? '编辑 Action' : '新建 Action'}</DialogTitle>
          <DialogDescription>
            字段为 PRD 13.5 全集；Client Action 不允许声明正式业务写入。
          </DialogDescription>
        </DialogHeader>

        <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
          <div className='space-y-1.5'>
            <Label htmlFor='action-name'>
              名称<span className='text-destructive'>（必填）</span>
            </Label>
            <Input
              id='action-name'
              value={form.name}
              onChange={(event) => set('name', event.target.value)}
              placeholder='如 ui.highlight_ticket'
              aria-invalid={Boolean(error) || undefined}
            />
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='action-capability'>Capability</Label>
            <Input
              id='action-capability'
              value={form.capability}
              onChange={(event) => set('capability', event.target.value)}
              placeholder='presentation / navigation / user_interaction…'
            />
          </div>
          <div className='space-y-1.5'>
            <Label>Risk</Label>
            <Select
              value={form.risk}
              onValueChange={(value) => set('risk', value as ActionContract['risk'])}
            >
              <SelectTrigger className='w-full' aria-label='选择风险级别'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {RISK_OPTIONS.map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1.5'>
            <Label>执行模式（Execution Mode）</Label>
            <Select
              value={form.executionMode}
              onValueChange={(value) =>
                set('executionMode', value as ActionContract['executionMode'])
              }
            >
              <SelectTrigger className='w-full' aria-label='选择执行模式'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {EXECUTION_MODE_OPTIONS.map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='action-timeout'>Timeout（ms）</Label>
            <Input
              id='action-timeout'
              type='number'
              min={1}
              value={form.timeoutMs}
              onChange={(event) => set('timeoutMs', event.target.value)}
            />
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='action-max-result'>Max Result Bytes（可选）</Label>
            <Input
              id='action-max-result'
              type='number'
              min={1}
              value={form.maxResultBytes}
              onChange={(event) => set('maxResultBytes', event.target.value)}
            />
          </div>
          <div className='space-y-1.5 md:col-span-2'>
            <Label htmlFor='action-description'>描述</Label>
            <Input
              id='action-description'
              value={form.description}
              onChange={(event) => set('description', event.target.value)}
              placeholder='该 Client Action 的行为说明'
            />
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='action-routes'>Allowed Routes（可选，逗号分隔）</Label>
            <Input
              id='action-routes'
              value={form.allowedRoutes}
              onChange={(event) => set('allowedRoutes', event.target.value)}
              placeholder='如 /risk, /tickets'
            />
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='action-bindings'>Resource Bindings（可选，逗号分隔）</Label>
            <Input
              id='action-bindings'
              value={form.resourceBindings}
              onChange={(event) => set('resourceBindings', event.target.value)}
              placeholder='如 client-action:ui'
            />
          </div>
          <div className='space-y-1.5 md:col-span-2'>
            <Label htmlFor='action-parameters'>入参 Schema（可选，紧凑 JSON 字符串）</Label>
            <Textarea
              id='action-parameters'
              value={form.parametersSchema}
              onChange={(event) => set('parametersSchema', event.target.value)}
              placeholder='如 {"type":"object","properties":{"ticketId":{"type":"string"}}}'
              rows={2}
              className='font-mono text-xs'
            />
          </div>
          <div className='space-y-1.5 md:col-span-2'>
            <Label htmlFor='action-result'>回执 Schema（可选，紧凑 JSON 字符串）</Label>
            <Textarea
              id='action-result'
              value={form.resultSchema}
              onChange={(event) => set('resultSchema', event.target.value)}
              placeholder='如 {"type":"object","properties":{"highlighted":{"type":"boolean"}}}'
              rows={2}
              className='font-mono text-xs'
            />
          </div>
          <div className='flex items-center gap-6 md:col-span-2'>
            <label htmlFor='action-requires-controller' className='flex items-center gap-2 text-sm'>
              <Checkbox
                id='action-requires-controller'
                checked={form.requiresController}
                onCheckedChange={(checked) => set('requiresController', checked === true)}
              />
              Requires Controller
            </label>
            <label htmlFor='action-requires-confirmation' className='flex items-center gap-2 text-sm'>
              <Checkbox
                id='action-requires-confirmation'
                checked={form.requiresUserConfirmation}
                onCheckedChange={(checked) => set('requiresUserConfirmation', checked === true)}
              />
              Requires User Confirmation
            </label>
          </div>
        </div>

        {error && <p className='text-destructive text-xs'>{error}</p>}

        <DialogFooter>
          <Button variant='outline' onClick={onCancel}>
            取消
          </Button>
          <Button disabled={Boolean(error)} onClick={submit}>
            保存到 Draft
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
