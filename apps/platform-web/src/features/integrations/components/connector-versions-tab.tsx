'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { JsonBlock } from '@/components/platform/json-block';
import { StatusBadge } from '@/components/platform/status-badge';
import type { Connector } from '@/lib/platform/types';
import { formatDateTime } from '@/lib/platform/format';

const VERSION_RULES = [
  'Published Revision 不可编辑，只能被新版本替代',
  '任何修改都会创建新的 Revision 并生成新 digest，不会原地覆盖',
  'Deprecated Revision 继续服务既有绑定，直到绑定显式升级',
  'Revoked Revision 立即 fail closed：新调用被拒绝，运行中调用按超时策略收敛',
  '绑定升级必须显式声明 expected revision（Compare-And-Swap），防止并发误升级',
  '任意两个 Revision 可生成版本 Diff（字段级对比，含 digest 变化）',
  '回滚不是复活旧状态，而是创建一条指向旧 Revision 的新 Rollout 记录'
];

/** 按修订号推导该版本的可Diff配置快照（确定性演示数据）。 */
function revisionSnapshot(connector: Connector, revision: number) {
  return {
    id: connector.id,
    revision,
    baseUri: connector.baseUri,
    manifestPath: connector.manifestPath,
    invokePath: connector.invokePath,
    reconcilePath: connector.reconcilePath,
    protocolVersions: connector.protocolVersions.slice(0, revision === connector.latestRevision ? undefined : 1),
    timeoutPolicy: {
      connectSeconds: connector.timeoutPolicy.connectSeconds,
      readSeconds: connector.timeoutPolicy.readSeconds + (connector.latestRevision - revision)
    },
    retryPolicy: {
      maxRetries: Math.max(1, connector.retryPolicy.maxRetries - (connector.latestRevision - revision)),
      backoff: connector.retryPolicy.backoff
    }
  };
}

/** Connector 版本管理（PRD 11.2）：版本表 + 版本规则 + Diff + 绑定升级。 */
export function ConnectorVersionsTab({
  connector,
  bindingsCount
}: {
  connector: Connector;
  bindingsCount: number;
}) {
  const [diffRevisions, setDiffRevisions] = useState<[number, number] | null>(null);
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  const [expectedRevision, setExpectedRevision] = useState(String(connector.latestRevision));

  const revisions = Array.from({ length: Math.min(3, connector.latestRevision) }, (_, index) =>
    connector.latestRevision - index
  ).toReversed();

  const runUpgrade = () => {
    const target = Number(expectedRevision);
    if (!Number.isInteger(target) || target < 1 || target > connector.latestRevision) {
      toast.error('expected revision 无效', { description: `需要 1 到 ${connector.latestRevision} 之间的整数` });
      return;
    }
    setUpgradeOpen(false);
    toast.success(`Binding 升级已提交（演示）`, {
      description: `expected revision = ${target}，将按 CAS 语义应用到 ${bindingsCount} 个绑定`
    });
  };

  return (
    <div className='flex flex-col gap-4'>
      <Card className='py-0'>
        <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
          <CardTitle className='text-sm'>版本历史（演示最近 {revisions.length} 个）</CardTitle>
          <Button variant='outline' size='sm' onClick={() => setUpgradeOpen(true)}>
            升级 Binding 到 rev {connector.latestRevision}
          </Button>
        </CardHeader>
        <CardContent className='p-0'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Revision</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>说明</TableHead>
                <TableHead>Updated At</TableHead>
                <TableHead className='text-right'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {revisions.map((revision) => {
                const isLatest = revision === connector.latestRevision;
                const isBound = revision === connector.boundRevision;
                return (
                  <TableRow key={revision}>
                    <TableCell className='font-mono text-xs font-medium'>rev {revision}</TableCell>
                    <TableCell>
                      <StatusBadge tone={isLatest ? 'success' : 'draft'} withDot={false}>
                        {isLatest ? 'Published' : 'Deprecated'}
                      </StatusBadge>
                    </TableCell>
                    <TableCell className='text-muted-foreground text-xs'>
                      {isLatest
                        ? '当前最新版本'
                        : `历史版本${isBound ? '（仍被绑定引用）' : ''}`}
                    </TableCell>
                    <TableCell className='text-muted-foreground text-xs'>
                      {formatDateTime(connector.updatedAt)}
                    </TableCell>
                    <TableCell className='text-right'>
                      <Button
                        variant='outline'
                        size='sm'
                        disabled={revisions.length < 2 || revision === revisions[0]}
                        onClick={() => setDiffRevisions([revision, revision - 1])}
                      >
                        查看 Diff
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>版本规则（PRD 11.2）</CardTitle>
        </CardHeader>
        <CardContent className='p-4'>
          <ol className='list-decimal space-y-1.5 pl-5 text-sm'>
            {VERSION_RULES.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <Dialog open={diffRevisions !== null} onOpenChange={(open) => !open && setDiffRevisions(null)}>
        <DialogContent className='sm:max-w-3xl'>
          <DialogHeader>
            <DialogTitle>
              Revision Diff · rev {diffRevisions?.[0]} → rev {diffRevisions?.[1]}
            </DialogTitle>
            <DialogDescription>字段级对比，仅用于演示版本差异（PRD 11.2）。</DialogDescription>
          </DialogHeader>
          <div className='grid grid-cols-1 gap-3 lg:grid-cols-2'>
            <JsonBlock
              title={`rev ${diffRevisions?.[0] ?? ''}`}
              value={diffRevisions ? revisionSnapshot(connector, diffRevisions[0]) : {}}
              maxHeight={280}
            />
            <JsonBlock
              title={`rev ${diffRevisions?.[1] ?? ''}`}
              value={diffRevisions ? revisionSnapshot(connector, diffRevisions[1]) : {}}
              maxHeight={280}
            />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={upgradeOpen} onOpenChange={setUpgradeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>升级 Binding 到 rev {connector.latestRevision}</DialogTitle>
            <DialogDescription>
              绑定升级采用 Compare-And-Swap：必须显式确认 expected revision，防止并发误升级。
            </DialogDescription>
          </DialogHeader>
          <div className='space-y-1.5'>
            <Label htmlFor='expected-revision'>Expected Revision（必填）</Label>
            <Input
              id='expected-revision'
              className='font-mono'
              value={expectedRevision}
              onChange={(event) => setExpectedRevision(event.target.value)}
            />
            <p className='text-muted-foreground text-xs'>
              当前绑定 rev {connector.boundRevision} · 最新 rev {connector.latestRevision} · 影响绑定 {bindingsCount} 个
            </p>
          </div>
          <DialogFooter>
            <Button variant='outline' onClick={() => setUpgradeOpen(false)}>
              取消
            </Button>
            <Button onClick={runUpgrade}>确认升级</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
