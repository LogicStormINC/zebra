'use client';

import { useMemo } from 'react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Icons } from '@/components/icons';
import { JsonBlock } from '@/components/platform/json-block';
import { StatusBadge } from '@/components/platform/status-badge';
import { cn } from '@/lib/utils';
import type { BackendManifest, ManifestTool } from '@/lib/platform/types';

const SECRET_KEY_PATTERN = /secret|password|api[_-]?key|token|credential/i;
const SCHEMA_MAX_BYTES = 8192;

export type ValidationRule = { label: string; passed: boolean; detail: string };

/** 实时校验规则（PRD 12.3）。 */
export function validateTools(tools: ManifestTool[], vocabulary: string[]): ValidationRule[] {
  const names = tools.map((tool) => tool.name);
  const duplicated = new Set(names.filter((name, index) => names.indexOf(name) !== index));

  const unknownCapabilities = tools.filter(
    (tool) => !vocabulary.includes(tool.capability) && !tool.capability.includes(':')
  );

  const missingIdempotency = tools.filter(
    (tool) => tool.risk !== 'read' && tool.idempotency === 'none'
  );

  const oversized = tools.filter(
    (tool) => JSON.stringify(tool.argumentSchema).length > SCHEMA_MAX_BYTES
  );

  const secretFields = tools.filter((tool) => {
    const keys = Object.keys(tool.argumentSchema ?? {});
    const propertyKeys = (
      (tool.argumentSchema as { properties?: Record<string, unknown> }).properties
        ? Object.keys((tool.argumentSchema as { properties: Record<string, unknown> }).properties)
        : []
    ) as string[];
    return [...keys, ...propertyKeys].some((key) => SECRET_KEY_PATTERN.test(key));
  });

  return [
    {
      label: 'Tool Name 全局唯一',
      passed: duplicated.size === 0,
      detail:
        duplicated.size === 0
          ? `共 ${tools.length} 个 tool，无重名`
          : `重复：${Array.from(duplicated).join('、')}`
    },
    {
      label: 'Capability 来自词汇表',
      passed: unknownCapabilities.length === 0,
      detail:
        unknownCapabilities.length === 0
          ? '全部 capability 均在平台词汇表或为合法 namespace:action 形式'
          : unknownCapabilities.map((tool) => tool.name).join('、')
    },
    {
      label: 'Write Tool 必须声明 Idempotency',
      passed: missingIdempotency.length === 0,
      detail:
        missingIdempotency.length === 0
          ? '全部 write tool 已声明幂等性'
          : missingIdempotency.map((tool) => tool.name).join('、')
    },
    {
      label: `Schema 大小 ≤ ${SCHEMA_MAX_BYTES} bytes`,
      passed: oversized.length === 0,
      detail:
        oversized.length === 0
          ? '全部 schema 在上限内'
          : oversized.map((tool) => tool.name).join('、')
    },
    {
      label: '不得包含 Secret 字段',
      passed: secretFields.length === 0,
      detail:
        secretFields.length === 0
          ? '未发现敏感命名字段'
          : secretFields.map((tool) => tool.name).join('、')
    }
  ];
}

type ChecklistStatus = 'passed' | 'pending';

/** 发布前检查清单（PRD 12.5）：由校验结果与 manifest 状态推导。 */
function buildChecklist(
  manifest: BackendManifest,
  rules: ValidationRule[]
): {
  name: string;
  status: ChecklistStatus;
  note: string;
}[] {
  const rulePassed = (index: number) => rules[index]?.passed ?? false;
  const writeTools = manifest.tools.filter((tool) => tool.risk !== 'read');
  return [
    {
      name: 'Schema Validation',
      status: rulePassed(0) && rulePassed(3) && rulePassed(4) ? 'passed' : 'pending',
      note: '结构、大小与敏感字段'
    },
    { name: 'Digest', status: 'passed', note: '内容寻址自动计算' },
    {
      name: 'Scope',
      status: manifest.tools.every((tool) => tool.grantScopes.length > 0) ? 'passed' : 'pending',
      note: '全部 tool 声明 Grant Scope'
    },
    { name: 'Resource Binding', status: 'passed', note: 'Namespace Binding 引用检查（演示）' },
    {
      name: 'Risk',
      status: manifest.tools.every((tool) => tool.risk !== undefined) ? 'passed' : 'pending',
      note: '风险分级完整'
    },
    { name: 'Idempotency', status: rulePassed(2) ? 'passed' : 'pending', note: '写操作幂等声明' },
    {
      name: 'Reconcile',
      status: writeTools.every((tool) => tool.reconcileCapable) ? 'passed' : 'pending',
      note: '写操作对账能力'
    },
    { name: 'Compatibility', status: 'passed', note: '协议版本兼容（演示）' },
    {
      name: 'Conformance',
      status: manifest.conformance === 'passed' ? 'passed' : 'pending',
      note: manifest.conformance === 'passed' ? '最近一次已通过' : '等待 Conformance Run'
    }
  ];
}

/** 三栏编辑器右栏：JSON 预览 + 实时校验 + 发布前检查清单。 */
export function ManifestValidationPanel({
  manifest,
  tools,
  vocabulary,
  dirty
}: {
  manifest: BackendManifest;
  tools: ManifestTool[];
  vocabulary: string[];
  dirty: boolean;
}) {
  const rules = useMemo(() => validateTools(tools, vocabulary), [tools, vocabulary]);
  const checklist = useMemo(() => buildChecklist(manifest, rules), [manifest, rules]);
  const allPassed = rules.every((rule) => rule.passed);

  const editedManifest = useMemo(
    () => ({
      id: manifest.id,
      protocolVersion: manifest.protocolVersion,
      revision: manifest.revision,
      digest: manifest.digest,
      tools
    }),
    [manifest.id, manifest.protocolVersion, manifest.revision, manifest.digest, tools]
  );

  return (
    <div className='flex flex-col gap-4 overflow-y-auto p-4'>
      <JsonBlock
        title={dirty ? 'manifest.json（本地未保存修改）' : 'manifest.json'}
        value={editedManifest}
        maxHeight={260}
      />

      <div>
        <p className='mb-2 flex items-center gap-2 text-sm font-semibold'>
          <Icons.checks className='size-4' />
          实时校验
          <StatusBadge tone={allPassed ? 'success' : 'failure'} withDot={false}>
            {allPassed ? '全部通过' : '存在失败项'}
          </StatusBadge>
        </p>
        <div className='space-y-1.5'>
          {rules.map((rule) => (
            <div
              key={rule.label}
              className={cn(
                'flex items-start justify-between gap-2 rounded-lg border px-3 py-2',
                rule.passed ? 'border-emerald-500/30' : 'border-red-500/40'
              )}
            >
              <div className='min-w-0'>
                <p className='text-xs font-medium'>{rule.label}</p>
                <p className='text-muted-foreground truncate text-xs'>{rule.detail}</p>
              </div>
              <StatusBadge tone={rule.passed ? 'success' : 'failure'} withDot={false}>
                {rule.passed ? 'Pass' : 'Fail'}
              </StatusBadge>
            </div>
          ))}
        </div>
      </div>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>发布前检查清单</CardTitle>
        </CardHeader>
        <CardContent className='divide-y p-0'>
          {checklist.map((item) => (
            <div key={item.name} className='flex items-center justify-between gap-2 px-4 py-2'>
              <div className='min-w-0'>
                <p className='text-xs font-medium'>{item.name}</p>
                <p className='text-muted-foreground truncate text-xs'>{item.note}</p>
              </div>
              <StatusBadge tone={item.status === 'passed' ? 'success' : 'waiting'} withDot={false}>
                {item.status === 'passed' ? '已通过' : '待检查'}
              </StatusBadge>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
