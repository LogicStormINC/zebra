'use client';

import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Icons } from '@/components/icons';
import { EmptyState } from '@/components/platform/empty-state';
import { PageHeader } from '@/components/platform/page-header';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import type { BackendManifest, ManifestTool } from '@/lib/platform/types';
import { CONFORMANCE_LABELS, REVISION_STATUS_LABELS } from '../lib/labels';
import { ManifestToolForm } from './manifest-tool-form';
import { ManifestValidationPanel } from './manifest-validation';

/** 平台能力词汇表（演示；实际由平台 Policy 下发）。 */
const CAPABILITY_VOCABULARY = [
  'position:read',
  'risk:read',
  'ticket:write',
  'content:read',
  'policy:read',
  'report:read',
  'test:read',
  'test:write'
];

/** 三栏 Manifest 编辑器（PRD 12.4）：Tool 列表 / Contract 表单 / JSON 与校验。 */
export function ManifestEditor({ manifest }: { manifest: BackendManifest }) {
  const [tools, setTools] = useState<ManifestTool[]>(manifest.tools);
  const [selectedName, setSelectedName] = useState<string>(manifest.tools[0]?.name ?? '');

  const dirty = useMemo(
    () => JSON.stringify(tools) !== JSON.stringify(manifest.tools),
    [tools, manifest.tools]
  );
  const selected = tools.find((tool) => tool.name === selectedName) ?? null;

  const updateTool = (next: ManifestTool) => {
    setTools((prev) => prev.map((tool) => (tool.name === selectedName ? next : tool)));
    if (next.name !== selectedName) setSelectedName(next.name);
  };

  const createTool = () => {
    const index = tools.length + 1;
    const candidate = `custom.tool_${index}`;
    if (tools.some((tool) => tool.name === candidate)) {
      toast.error('已存在同名 Tool，请先重命名');
      return;
    }
    const tool: ManifestTool = {
      name: candidate,
      description: '新建 Tool（未发布）',
      capability: 'test:read',
      grantScopes: [],
      risk: 'read',
      idempotency: 'none',
      timeoutSeconds: 10,
      maxOutputBytes: 16384,
      reconcileCapable: false,
      argumentSchema: { type: 'object', properties: {} }
    };
    setTools((prev) => [...prev, tool]);
    setSelectedName(tool.name);
    toast.success('已新建 Tool 草稿（本地）');
  };

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title={
          <span className='flex flex-wrap items-center gap-2'>
            <span className='font-mono'>{manifest.id}</span>
            <span className='text-muted-foreground font-mono text-sm'>rev {manifest.revision}</span>
            <StatusBadge tone={lifecycleTone(manifest.status)} withDot={false}>
              {REVISION_STATUS_LABELS[manifest.status]}
            </StatusBadge>
            <StatusBadge tone={lifecycleTone(manifest.conformance)} withDot={false}>
              Conformance {CONFORMANCE_LABELS[manifest.conformance]}
            </StatusBadge>
            {dirty && <StatusBadge tone='warning'>有未创建 Revision 的修改</StatusBadge>}
          </span>
        }
        description={`Backend Manifest 编辑器 · host ${manifest.hostAppId} · ${manifest.protocolVersion} · ${manifest.tools.length} tools（Read ${manifest.readTools} / Write ${manifest.writeTools} / Reconcile ${manifest.reconcileTools}）`}
        actions={
          <RiskConfirmDialog
            trigger={
              <Button>
                <Icons.manifest data-icon='inline-start' />
                创建新 Revision
              </Button>
            }
            title='创建新 Manifest Revision'
            impact={`基于当前编辑内容生成 rev ${manifest.revision + 1} 草稿，发布前需通过 Conformance；已发布绑定仍引用 rev ${manifest.revision}。`}
            irreversibility='已发布 Revision 永不改写；新 Revision 发布后旧版本进入 Deprecated。'
            currentRevision={`rev ${manifest.revision}`}
            targetRevision={`rev ${manifest.revision + 1}`}
            actionLabel='创建 Revision'
            onConfirm={(reason) => {
              if (!dirty) {
                toast.info('当前内容与已发布 Revision 一致（演示）', { description: '修改 Tool 契约后再创建' });
                return;
              }
              toast.success(`新 Revision rev ${manifest.revision + 1} 已创建（演示）`, {
                description: `审计原因：${reason}`
              });
            }}
          />
        }
        meta={
          <div className='flex flex-wrap items-center gap-x-4 gap-y-1.5'>
            <span>Host：<span className='font-mono'>{manifest.hostAppId}</span></span>
            <span>Created By：{manifest.createdBy}</span>
            <span>Created At：{formatDateTime(manifest.createdAt)}</span>
            <span>
              Digest：<span className='font-mono'>{manifest.digest.slice(0, 16)}…</span>
            </span>
          </div>
        }
      />

      <div className='flex flex-1 flex-col gap-4 p-4 md:px-6'>
        <Alert>
          <Icons.warning className='text-amber-500' />
          <AlertTitle>已发布 Revision 不可编辑</AlertTitle>
          <AlertDescription>
            本编辑器中的修改仅保留在本地 state；确认后需「创建新 Revision」生成新 digest 并走发布流程（PRD 12.2）。
          </AlertDescription>
        </Alert>

        <div className='grid grid-cols-1 gap-4 lg:grid-cols-[240px_minmax(0,1fr)_380px]'>
          {/* 左栏：Tool 列表 */}
          <div className='flex max-h-[640px] flex-col rounded-lg border'>
            <div className='flex items-center justify-between gap-2 border-b px-3 py-2.5'>
              <p className='text-sm font-semibold'>Tools（{tools.length}）</p>
              <Button variant='outline' size='icon-sm' aria-label='新建 Tool' onClick={createTool}>
                <Icons.add className='size-4' />
              </Button>
            </div>
            <div className='flex flex-1 flex-col overflow-y-auto p-1.5'>
              {tools.map((tool) => (
                <button
                  key={tool.name}
                  type='button'
                  onClick={() => setSelectedName(tool.name)}
                  className={cn(
                    'flex flex-col items-start gap-0.5 rounded-md px-2.5 py-2 text-left transition-colors',
                    tool.name === selectedName ? 'bg-muted' : 'hover:bg-muted/60'
                  )}
                >
                  <span className='w-full truncate font-mono text-xs font-medium'>{tool.name}</span>
                  <span className='text-muted-foreground w-full truncate text-[10px]'>
                    {tool.capability} · {tool.risk}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* 中栏：Contract 表单 */}
          <div className='flex max-h-[640px] flex-col rounded-lg border'>
            <div className='border-b px-3 py-2.5'>
              <p className='text-sm font-semibold'>Tool Contract</p>
            </div>
            <ManifestToolForm
              tool={selected}
              capabilityVocabulary={CAPABILITY_VOCABULARY}
              onChange={updateTool}
            />
          </div>

          {/* 右栏：JSON + 校验 + 检查清单 */}
          <div className='flex max-h-[640px] flex-col rounded-lg border'>
            <div className='border-b px-3 py-2.5'>
              <p className='text-sm font-semibold'>JSON 与校验</p>
            </div>
            <ManifestValidationPanel
              manifest={manifest}
              tools={tools}
              vocabulary={CAPABILITY_VOCABULARY}
              dirty={dirty}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Manifest 不存在时的空态。 */
export function ManifestNotFound({ manifestId }: { manifestId: string }) {
  return (
    <div className='flex flex-1 flex-col'>
      <EmptyState
        title='未找到该 Manifest'
        description={`Backend Manifest ${manifestId} 不存在，请从列表重新进入`}
        icon='manifest'
      />
    </div>
  );
}
