'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
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
import type { ReadableContract } from '@/lib/platform/types';
import { DRAFT_TOAST_DESCRIPTION, parseList, parsePositiveInt } from './contract-form-shared';
import { SENSITIVITY_LABELS, UPDATE_STRATEGY_LABELS } from './labels';

/** Readable 契约编辑表单（PRD 13.4 / 35.4.1）：字段全集，保存到 Draft。 */

const SENSITIVITY_OPTIONS = Object.entries(SENSITIVITY_LABELS) as [
  ReadableContract['sensitivity'],
  string
][];
const UPDATE_STRATEGY_OPTIONS = Object.entries(UPDATE_STRATEGY_LABELS) as [
  ReadableContract['updateStrategy'],
  string
][];

type ReadableFormState = {
  name: string;
  description: string;
  sensitivity: ReadableContract['sensitivity'];
  maxBytes: string;
  updateStrategy: ReadableContract['updateStrategy'];
  contextPriority: string;
  jsonSchema: string;
  redactionRules: string;
  resourceBinding: string;
};

function readableFormFrom(initial: ReadableContract | null): ReadableFormState {
  return {
    name: initial?.name ?? '',
    description: initial?.description ?? '',
    sensitivity: initial?.sensitivity ?? 'public',
    maxBytes: String(initial?.maxBytes ?? 1024),
    updateStrategy: initial?.updateStrategy ?? 'on_change',
    contextPriority: String(initial?.contextPriority ?? 10),
    jsonSchema: initial?.jsonSchema ?? '',
    redactionRules: initial?.redactionRules?.join(', ') ?? '',
    resourceBinding: initial?.resourceBinding ?? ''
  };
}

/** 前端可做的 Readable 校验（PRD 13.4）：名称必填。 */
function readableValidationError(form: ReadableFormState): string | null {
  if (!form.name.trim()) return '名称必填：Readable Contract 必须有唯一名称';
  return null;
}

export function ReadableFormDialog({
  initial,
  profileRevision,
  onCancel,
  onSubmit
}: {
  /** null 表示新建。 */
  initial: ReadableContract | null;
  profileRevision: number;
  onCancel: () => void;
  onSubmit: (contract: ReadableContract) => void;
}) {
  const [form, setForm] = useState<ReadableFormState>(() => readableFormFrom(initial));
  const error = readableValidationError(form);
  const set = <K extends keyof ReadableFormState>(key: K, value: ReadableFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const submit = () => {
    const contract: ReadableContract = {
      name: form.name.trim(),
      description: form.description.trim(),
      sensitivity: form.sensitivity,
      maxBytes: parsePositiveInt(form.maxBytes, 1024),
      updateStrategy: form.updateStrategy,
      contextPriority: parsePositiveInt(form.contextPriority, 10),
      jsonSchema: form.jsonSchema.trim() || undefined,
      redactionRules: parseList(form.redactionRules),
      resourceBinding: form.resourceBinding.trim() || undefined
    };
    onSubmit(contract);
    toast.success(`${initial ? 'Readable 已保存到 Draft' : '新 Readable 已保存到 Draft'}：${contract.name}`, {
      description: `${DRAFT_TOAST_DESCRIPTION}（当前 rev ${profileRevision}）`
    });
    onCancel();
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className='max-h-[85vh] max-w-2xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{initial ? '编辑 Readable' : '新建 Readable'}</DialogTitle>
          <DialogDescription>
            字段为 PRD 13.4 全集；保存到 Draft 后随 Profile 新 Revision 发布。
          </DialogDescription>
        </DialogHeader>

        <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
          <div className='space-y-1.5'>
            <Label htmlFor='readable-name'>
              名称<span className='text-destructive'>（必填）</span>
            </Label>
            <Input
              id='readable-name'
              value={form.name}
              onChange={(event) => set('name', event.target.value)}
              placeholder='如 positions.selected_account'
              aria-invalid={Boolean(error) || undefined}
            />
          </div>
          <div className='space-y-1.5'>
            <Label>敏感度（Sensitivity）</Label>
            <Select
              value={form.sensitivity}
              onValueChange={(value) => set('sensitivity', value as ReadableContract['sensitivity'])}
            >
              <SelectTrigger className='w-full' aria-label='选择敏感度'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {SENSITIVITY_OPTIONS.map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}（{value}）
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1.5 md:col-span-2'>
            <Label htmlFor='readable-description'>描述</Label>
            <Input
              id='readable-description'
              value={form.description}
              onChange={(event) => set('description', event.target.value)}
              placeholder='注入 Agent 上下文的用途说明'
            />
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='readable-max-bytes'>Max Bytes</Label>
            <Input
              id='readable-max-bytes'
              type='number'
              min={1}
              value={form.maxBytes}
              onChange={(event) => set('maxBytes', event.target.value)}
            />
          </div>
          <div className='space-y-1.5'>
            <Label>更新策略（Update Strategy）</Label>
            <Select
              value={form.updateStrategy}
              onValueChange={(value) =>
                set('updateStrategy', value as ReadableContract['updateStrategy'])
              }
            >
              <SelectTrigger className='w-full' aria-label='选择更新策略'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {UPDATE_STRATEGY_OPTIONS.map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}（{value}）
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='readable-priority'>Context Priority</Label>
            <Input
              id='readable-priority'
              type='number'
              value={form.contextPriority}
              onChange={(event) => set('contextPriority', event.target.value)}
            />
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='readable-binding'>Resource Binding（可选）</Label>
            <Input
              id='readable-binding'
              value={form.resourceBinding}
              onChange={(event) => set('resourceBinding', event.target.value)}
              placeholder='如 trench.positions:read'
            />
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='readable-redaction'>脱敏规则（可选，逗号分隔）</Label>
            <Input
              id='readable-redaction'
              value={form.redactionRules}
              onChange={(event) => set('redactionRules', event.target.value)}
              placeholder='如 mask/account, drop/email'
            />
          </div>
          <div className='space-y-1.5 md:col-span-2'>
            <Label htmlFor='readable-schema'>JSON Schema（可选，紧凑字符串）</Label>
            <Textarea
              id='readable-schema'
              value={form.jsonSchema}
              onChange={(event) => set('jsonSchema', event.target.value)}
              placeholder='如 {"type":"string","pattern":"^RPT-"}'
              rows={2}
              className='font-mono text-xs'
            />
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
