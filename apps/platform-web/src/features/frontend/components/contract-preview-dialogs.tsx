'use client';

import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatBytes } from '@/lib/platform/format';
import type { ReadableContract } from '@/lib/platform/types';
import { SENSITIVITY_LABELS, SENSITIVITY_TONES } from './labels';
import { SensitivityBadge } from './sensitivity-badge';

/**
 * Readable 契约的静态预览 Dialog（PRD 13.4）：
 * 脱敏预览（规则 + 脱敏前后示例）与示例值校验（Schema + 示例值通过）。
 */

/** 规则名 → 静态脱敏前后示例。 */
const REDACTION_EXAMPLES: Record<string, { before: string; after: string }> = {
  'mask/account': { before: 'ACC-8891-4302', after: 'ACC-****-****' },
  'mask/report_id': { before: 'RPT-2026-08-25', after: 'RPT-2026-**-**' },
  'mask/ticket_id': { before: 'TR-2291', after: 'TR-****' },
  'drop/email': { before: 'ops@trench.example', after: '[REDACTED]' },
  'drop/holder_name': { before: '持有人：张三', after: '持有人：[REDACTED]' }
};

function exampleFor(rule: string): { before: string; after: string } {
  return REDACTION_EXAMPLES[rule] ?? { before: 'raw-value-9f21', after: '[REDACTED]' };
}

/** 脱敏预览 Dialog：规则列表 + 脱敏前后示例（静态演示）。 */
export function RedactionPreviewDialog({
  readable,
  open,
  onOpenChange
}: {
  readable: ReadableContract | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const rules = readable?.redactionRules ?? [];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[85vh] max-w-lg overflow-y-auto'>
        {readable && (
          <>
            <DialogHeader>
              <DialogTitle>脱敏预览：{readable.name}</DialogTitle>
              <DialogDescription>
                注入 Agent 上下文前按 Redaction Rules 执行脱敏，平台仅保留脱敏摘要（静态示例）。
              </DialogDescription>
            </DialogHeader>

            <div className='space-y-4'>
              <div className='flex flex-wrap items-center gap-2'>
                <SensitivityBadge sensitivity={readable.sensitivity} />
                {rules.length === 0 ? (
                  <span className='text-muted-foreground text-sm'>
                    未配置脱敏规则：
                    {readable.sensitivity === 'public'
                      ? '公开数据按原文注入上下文'
                      : '建议按敏感度配置 Redaction Rules'}
                  </span>
                ) : (
                  rules.map((rule) => (
                    <Badge key={rule} variant='secondary' className='font-mono text-xs'>
                      {rule}
                    </Badge>
                  ))
                )}
              </div>

              <div className='rounded-lg border'>
                <div className='grid grid-cols-[9rem_1fr_1fr] gap-2 border-b bg-muted px-3 py-2 text-xs font-medium'>
                  <span>规则</span>
                  <span>脱敏前（原始值）</span>
                  <span>脱敏后（注入上下文）</span>
                </div>
                {rules.length === 0 ? (
                  <div className='px-3 py-2 text-xs'>
                    <div className='grid grid-cols-[9rem_1fr_1fr] gap-2'>
                      <span className='text-muted-foreground'>（无规则）</span>
                      <span className='font-mono'>RPT-2026-08-25</span>
                      <span className='font-mono'>RPT-2026-08-25（原文）</span>
                    </div>
                  </div>
                ) : (
                  rules.map((rule) => {
                    const example = exampleFor(rule);
                    return (
                      <div
                        key={rule}
                        className='grid grid-cols-[9rem_1fr_1fr] items-start gap-2 border-b px-3 py-2 text-xs last:border-0'
                      >
                        <span className='text-muted-foreground font-mono'>{rule}</span>
                        <span className='font-mono break-all'>{example.before}</span>
                        <span className='flex flex-col gap-1'>
                          <span className='font-mono break-all'>{example.after}</span>
                          <StatusBadge tone={example.after.includes('*') || example.after.includes('REDACTED') ? 'success' : 'draft'} withDot={false}>
                            已脱敏
                          </StatusBadge>
                        </span>
                      </div>
                    );
                  })
                )}
              </div>
              <p className='text-muted-foreground text-xs'>
                敏感度：{SENSITIVITY_LABELS[readable.sensitivity]}（{readable.sensitivity}）；平台事件与
                Trace 中只出现脱敏后的值与摘要，不落原始值。
              </p>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function prettySchema(schema: string | undefined): string {
  if (!schema) return '（未声明 JSON Schema，示例值仅做大小校验）';
  try {
    return JSON.stringify(JSON.parse(schema), null, 2);
  } catch {
    return `${schema}\n（注意：该字符串不是合法 JSON，发布前会校验失败）`;
  }
}

/** 按声明推断静态示例值（确定性，不使用随机）。 */
function sampleValue(readable: ReadableContract): string {
  if (readable.name === 'page.route') return '"/risk/reports/2026-08-25"';
  if (readable.name === 'risk.report_id') return '"RPT-2026-08-25"';
  if (readable.name === 'positions.selected_account') return '"ACC-8891-4302"';
  const schema = readable.jsonSchema ?? '';
  if (schema.includes('"type":"number"') || schema.includes('"type":"integer"')) return '42';
  if (schema.includes('"type":"boolean"')) return 'true';
  if (schema.includes('"type":"array"')) return '["TR-2291","TR-2287"]';
  if (schema.includes('"type":"object"')) return '{"ticketId":"TR-2291"}';
  return '"sample-value"';
}

/** 示例值校验 Dialog：JSON Schema + 示例值通过（静态演示）。 */
export function SampleValidationDialog({
  readable,
  open,
  onOpenChange
}: {
  readable: ReadableContract | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const sample = readable ? sampleValue(readable) : '';
  const sampleBytes = sample.length;
  const withinLimit = readable ? sampleBytes <= readable.maxBytes : false;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[85vh] max-w-lg overflow-y-auto'>
        {readable && (
          <>
            <DialogHeader>
              <DialogTitle>示例值校验：{readable.name}</DialogTitle>
              <DialogDescription>
                Frontend Conformance 会用示例值跑一遍 Schema 与大小上限（静态示例，结果为通过）。
              </DialogDescription>
            </DialogHeader>

            <div className='space-y-4'>
              <div className='space-y-1.5'>
                <p className='text-muted-foreground text-xs'>JSON Schema</p>
                <pre className='bg-muted/40 overflow-auto rounded-lg border p-3 font-mono text-xs leading-relaxed'>
                  {prettySchema(readable.jsonSchema)}
                </pre>
              </div>

              <div className='space-y-1.5'>
                <p className='text-muted-foreground text-xs'>示例值（静态）</p>
                <pre className='bg-muted/40 overflow-auto rounded-lg border p-3 font-mono text-xs leading-relaxed'>
                  {sample}
                </pre>
              </div>

              <div className='space-y-2 rounded-lg border px-3 py-2 text-xs'>
                <div className='flex items-center justify-between'>
                  <span className='text-muted-foreground'>Schema 校验</span>
                  <StatusBadge tone='success' withDot={false}>
                    pass
                  </StatusBadge>
                </div>
                <div className='flex items-center justify-between'>
                  <span className='text-muted-foreground'>
                    大小校验：{sampleBytes} B / 上限 {formatBytes(readable.maxBytes)}
                  </span>
                  <StatusBadge tone={withinLimit ? 'success' : 'failure'} withDot={false}>
                    {withinLimit ? 'pass' : 'fail'}
                  </StatusBadge>
                </div>
                <div className='flex items-center justify-between'>
                  <span className='text-muted-foreground'>敏感度</span>
                  <StatusBadge tone={SENSITIVITY_TONES[readable.sensitivity]} withDot={false}>
                    {SENSITIVITY_LABELS[readable.sensitivity]}（{readable.sensitivity}）
                  </StatusBadge>
                </div>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
