'use client';

import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/platform/status-badge';
import { RiskBadge } from '@/components/platform/risk-badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { Icons } from '@/components/icons';

const SAMPLE_MANIFEST = `{
  "protocolVersion": "zebra-manifest/1.2",
  "tools": [
    {
      "name": "demo.get_report",
      "description": "读取报告摘要",
      "capability": "report:read",
      "grantScopes": ["demo.report:read"],
      "risk": "read",
      "idempotency": "none",
      "timeoutSeconds": 10,
      "maxOutputBytes": 65536,
      "reconcileCapable": false,
      "argumentSchema": { "type": "object", "properties": { "report_id": { "type": "string" } }, "required": ["report_id"] }
    },
    {
      "name": "demo.create_ticket",
      "description": "创建工单（写操作）",
      "capability": "ticket:write",
      "grantScopes": ["demo.tickets:write"],
      "risk": "medium",
      "idempotency": "idempotency_key",
      "timeoutSeconds": 20,
      "maxOutputBytes": 16384,
      "reconcileCapable": true,
      "argumentSchema": { "type": "object", "properties": { "title": { "type": "string" } }, "required": ["title"] }
    }
  ]
}`;

const SECRET_KEY_PATTERN = /secret|password|api[_-]?key|token|credential/i;

type ParsedTool = {
  name?: string;
  risk?: string;
  idempotency?: string;
  capability?: string;
  timeoutSeconds?: number;
};

type ValidationResult = { label: string; passed: boolean; detail?: string };

/** Step 4 Backend Manifest（PRD 12）：粘贴 JSON + 解析校验 + Tool 摘要。 */
export function OnboardingStepManifest({
  value,
  onChange
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const [parsed, setParsed] = useState<{ tools: ParsedTool[]; results: ValidationResult[] } | null>(
    null
  );

  const canParse = value.trim().length > 0;

  const validate = () => {
    let decoded: unknown;
    try {
      decoded = JSON.parse(value);
    } catch (error) {
      const results = [
        {
          label: 'JSON 语法解析',
          passed: false,
          detail: error instanceof Error ? error.message : '无法解析'
        }
      ];
      setParsed({ tools: [], results });
      return;
    }

    const manifest = decoded as { tools?: ParsedTool[] };
    const tools = Array.isArray(manifest.tools) ? manifest.tools : [];
    const results: ValidationResult[] = [
      {
        label: 'JSON 语法解析',
        passed: true,
        detail: `解析为对象，protocolVersion ${(manifest as { protocolVersion?: string }).protocolVersion ?? '—'}`
      },
      {
        label: 'tools 为非空数组',
        passed: tools.length > 0,
        detail: tools.length > 0 ? `共 ${tools.length} 个 tool` : 'tools 缺失或为空'
      }
    ];

    if (tools.length > 0) {
      const names = tools.map((tool) => String(tool.name ?? ''));
      const duplicated = new Set(names.filter((name, index) => names.indexOf(name) !== index));
      results.push({
        label: 'Tool name 全局唯一',
        passed: duplicated.size === 0,
        detail: duplicated.size === 0 ? '无重复 name' : `重复：${Array.from(duplicated).join('、')}`
      });

      const missingIdempotency = tools.filter(
        (tool) => tool.risk && tool.risk !== 'read' && (!tool.idempotency || tool.idempotency === 'none')
      );
      results.push({
        label: 'Write tool 必须声明 Idempotency',
        passed: missingIdempotency.length === 0,
        detail:
          missingIdempotency.length === 0
            ? '全部 write tool 已声明幂等性'
            : missingIdempotency.map((tool) => tool.name).join('、')
      });

      const secretHits = Object.keys(manifest as Record<string, unknown>).filter((key) =>
        SECRET_KEY_PATTERN.test(key)
      );
      const toolSecretHits = tools.filter((tool) =>
        Object.keys(tool).some((key) => SECRET_KEY_PATTERN.test(key))
      );
      results.push({
        label: '不含 Secret 字段',
        passed: secretHits.length === 0 && toolSecretHits.length === 0,
        detail:
          secretHits.length === 0 && toolSecretHits.length === 0
            ? '未发现敏感字段'
            : `发现可疑字段：${[...secretHits, ...toolSecretHits.map((tool) => String(tool.name))].join('、')}`
      });
    }

    setParsed({ tools, results });
    const allPassed = results.every((result) => result.passed);
    if (allPassed) {
      toast.success('Manifest 解析校验通过（演示）');
    }
  };

  const summaryTools = useMemo(() => parsed?.tools ?? [], [parsed]);

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <p className='text-muted-foreground text-sm'>
          粘贴 Backend Manifest JSON，平台将执行 Schema 与安全校验（PRD 12.3）。
        </p>
        <div className='flex gap-2'>
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={() => {
              onChange(SAMPLE_MANIFEST);
              setParsed(null);
            }}
          >
            填入示例 Manifest
          </Button>
          <Button type='button' size='sm' disabled={!canParse} onClick={validate}>
            <Icons.check data-icon='inline-start' />
            解析校验
          </Button>
        </div>
      </div>

      <Textarea
        value={value}
        rows={12}
        placeholder='{ "protocolVersion": "zebra-manifest/1.2", "tools": [ … ] }'
        className='font-mono text-xs'
        onChange={(event) => {
          onChange(event.target.value);
          setParsed(null);
        }}
      />

      {parsed && (
        <>
          <Card className='py-0'>
            <CardHeader className='border-b px-4 py-3'>
              <CardTitle className='text-sm'>校验结果</CardTitle>
            </CardHeader>
            <CardContent className='divide-y p-0'>
              {parsed.results.map((result) => (
                <div key={result.label} className='flex items-center justify-between gap-3 px-4 py-2.5'>
                  <div className='min-w-0'>
                    <p className='text-sm font-medium'>{result.label}</p>
                    {result.detail && (
                      <p className='text-muted-foreground truncate font-mono text-xs'>{result.detail}</p>
                    )}
                  </div>
                  <StatusBadge tone={result.passed ? 'success' : 'failure'} withDot={false}>
                    {result.passed ? 'Pass' : 'Fail'}
                  </StatusBadge>
                </div>
              ))}
            </CardContent>
          </Card>

          {summaryTools.length > 0 && (
            <Card className='py-0'>
              <CardHeader className='border-b px-4 py-3'>
                <CardTitle className='text-sm'>Tool 摘要（{summaryTools.length}）</CardTitle>
              </CardHeader>
              <CardContent className='p-0'>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tool</TableHead>
                      <TableHead>Capability</TableHead>
                      <TableHead>Risk</TableHead>
                      <TableHead>Idempotency</TableHead>
                      <TableHead>Timeout</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {summaryTools.map((tool, index) => (
                      <TableRow key={tool.name ?? `tool-${index}`}>
                        <TableCell className='font-mono text-xs'>{tool.name ?? '—'}</TableCell>
                        <TableCell className='font-mono text-xs'>{tool.capability ?? '—'}</TableCell>
                        <TableCell>{tool.risk ? <RiskBadge risk={tool.risk} /> : '—'}</TableCell>
                        <TableCell className='text-xs'>
                          {tool.idempotency && tool.idempotency !== 'none'
                            ? tool.idempotency === 'idempotent'
                              ? '幂等'
                              : '幂等键'
                            : '—'}
                        </TableCell>
                        <TableCell className='text-xs tabular-nums'>
                          {tool.timeoutSeconds ? `${tool.timeoutSeconds}s` : '—'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
