'use client';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
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
import { EmptyState } from '@/components/platform/empty-state';
import { JsonBlock } from '@/components/platform/json-block';
import { DigestTag, MonoId } from '@/components/platform/mono-id';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import type { AgentRelease } from '@/lib/platform/types';
import { pseudoDigest, type DefinitionDetailData } from './definition-detail-data';

const LIFECYCLE_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

const CHANNEL_LABELS: Record<string, string> = {
  stable: 'Stable',
  canary: 'Canary',
  'dry-run': 'Dry Run'
};

/** Draft Tab（PRD 14.2）：8 个 Ref 字段 + Validate + Materialize Version。 */
export function DefinitionDraftTab({ data }: { data: DefinitionDetailData }) {
  const { definition } = data;
  const fields = [
    { label: 'Capability Profile Ref', value: definition.toolProfileId, hint: data.capabilityProfile?.name },
    { label: 'Model Policy Ref', value: definition.modelPolicyId, hint: data.modelPolicy?.name },
    { label: 'Tool Profile Ref', value: definition.toolProfileId, hint: data.capabilityProfile?.name },
    { label: 'Skill Snapshot Digest', value: `sha256:${pseudoDigest(`${definition.id}:skills:rev${definition.latestDraftRevision}`).slice(0, 24)}`, hint: '技能快照（不可变）' },
    { label: 'Memory Policy Ref', value: definition.memoryPolicyId ?? '（未启用）', hint: data.memoryPolicy?.name },
    { label: 'Security Policy Ref', value: data.securityPolicy?.id ?? 'pol_approval_high_risk', hint: data.securityPolicy?.name },
    { label: 'Evaluation Profile Ref', value: `evp_${pseudoDigest(`${definition.id}:eval`).slice(0, 8)}`, hint: '评测集配置' },
    { label: 'Runtime Profile Ref', value: definition.runtimeProfileId, hint: data.runtimePolicy?.name }
  ];

  return (
    <div className='flex flex-col gap-4'>
      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Draft rev {definition.latestDraftRevision} 的 8 个 Ref 字段</CardTitle>
        </CardHeader>
        <CardContent className='grid grid-cols-1 gap-4 p-4 md:grid-cols-2'>
          {fields.map((field) => (
            <div key={field.label} className='space-y-1.5'>
              <Label className='text-xs'>{field.label}</Label>
              <Input readOnly value={field.value} className='font-mono text-xs' />
              {field.hint && <p className='text-muted-foreground text-xs'>{field.hint}</p>}
            </div>
          ))}
        </CardContent>
      </Card>

      <div className='flex flex-wrap items-center gap-2'>
        <Button
          variant='outline'
          size='sm'
          onClick={() =>
            toast.success('Validate 已提交（演示）', {
              description: '8 个 Ref 将被逐一解析并校验 digest 与 revision 兼容性'
            })
          }
        >
          <Icons.circleCheck className='size-4' />
          Validate
        </Button>
        <RiskConfirmDialog
          trigger={
            <Button size='sm'>
              <Icons.agentRelease className='size-4' />
              Materialize Version
            </Button>
          }
          title='Materialize Version'
          impact={`将基于 Draft rev ${definition.latestDraftRevision} 创建不可变的新版本 v${definition.latestVersion + 1}`}
          irreversibility='版本一旦物化即不可修改，只能通过发布新版本覆盖'
          currentRevision={`draft rev ${definition.latestDraftRevision}`}
          targetRevision={`v${definition.latestVersion + 1}`}
          actionLabel='物化新版本'
          onConfirm={() => {
            // 演示操作：无真实写入
          }}
        />
        <p className='text-muted-foreground ml-auto max-w-md text-xs'>
          已发布 Version 不可原地编辑：对已发布版本的任何修改都会进入新的 Draft（rev{' '}
          {definition.latestDraftRevision}），经 Validate → Release Gate 后物化为下一个版本。
        </p>
      </div>
    </div>
  );
}

/** Versions Tab：v1..latestVersion 版本表 + Diff Dialog。 */
export function DefinitionVersionsTab({ data }: { data: DefinitionDetailData }) {
  const { definition, releases } = data;
  if (definition.latestVersion === 0) {
    return (
      <EmptyState
        icon='agentRelease'
        title='尚未物化任何版本'
        description='在 Draft Tab 点击 Materialize Version 后，这里会出现 v1 起的不可变版本记录'
      />
    );
  }

  const versions = Array.from({ length: definition.latestVersion }, (_, index) => {
    const version = index + 1;
    const release = releases.find((item) => item.version === version);
    return {
      version,
      digest: release?.digest ?? pseudoDigest(`${definition.id}:v${version}`),
      status: release ? release.status : 'draft',
      releasedAt: release?.releasedAt,
      releaseId: release?.id
    };
  }).toReversed();

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Version</TableHead>
            <TableHead>Digest</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Released At</TableHead>
            <TableHead className='text-right'>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {versions.map((version) => (
            <TableRow key={version.version}>
              <TableCell className='font-medium tabular-nums'>v{version.version}</TableCell>
              <TableCell>
                <DigestTag value={version.digest} />
              </TableCell>
              <TableCell>
                <StatusBadge tone={lifecycleTone(version.status)}>
                  {LIFECYCLE_LABELS[version.status] ?? version.status}
                </StatusBadge>
              </TableCell>
              <TableCell className='text-sm'>
                {version.releasedAt ? formatDateTime(version.releasedAt) : '—'}
              </TableCell>
              <TableCell className='text-right'>
                {version.version > 1 ? (
                  <VersionDiffDialog data={data} version={version.version} />
                ) : (
                  <span className='text-muted-foreground text-xs'>首个版本，无 Diff</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function VersionDiffDialog({ data, version }: { data: DefinitionDetailData; version: number }) {
  const buildPayload = (v: number) => {
    const release = data.releases.find((item) => item.version === v);
    return {
      definitionId: data.definition.id,
      version: v,
      digest: release?.digest ?? pseudoDigest(`${data.definition.id}:v${v}`),
      channel: release?.channel ?? 'unreleased',
      refs: {
        capabilityProfile: data.definition.toolProfileId,
        modelPolicy: data.definition.modelPolicyId,
        toolProfile: data.definition.toolProfileId,
        memoryPolicy: data.definition.memoryPolicyId ?? null,
        runtimeProfile: data.definition.runtimeProfileId
      }
    };
  };
  const previous = buildPayload(version - 1);
  const current = buildPayload(version);

  return (
    <Dialog>
      <DialogTrigger render={<Button variant='outline' size='sm' />}>
        查看 Diff
      </DialogTrigger>
      <DialogContent className='sm:max-w-3xl'>
        <DialogHeader>
          <DialogTitle>版本 Diff：v{version - 1} → v{version}</DialogTitle>
          <DialogDescription>左右对照两个不可变版本的引用快照</DialogDescription>
        </DialogHeader>
        <div className='grid grid-cols-1 gap-3 lg:grid-cols-2'>
          <JsonBlock title={`v${version - 1}.json`} value={previous} maxHeight={280} />
          <JsonBlock title={`v${version}.json`} value={current} maxHeight={280} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Release Tab：已发布 Release 卡片 + Revoke / Promote。 */
export function DefinitionReleaseTab({ data }: { data: DefinitionDetailData }) {
  if (data.releases.length === 0) {
    return (
      <EmptyState
        icon='agentRelease'
        title='该 Definition 尚无已发布 Release'
        description='物化版本并通过 Release Gate 后，即可发布到 stable / canary / dry-run 渠道'
      />
    );
  }

  return (
    <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
      {data.releases.map((release) => (
        <ReleaseCard key={release.id} release={release} />
      ))}
    </div>
  );
}

function ReleaseCard({ release }: { release: AgentRelease }) {
  return (
    <Card className='py-0'>
      <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
        <CardTitle className='flex items-center gap-2 text-sm'>
          <MonoId value={release.id} copyable={false} />
          <Badge variant='outline'>{CHANNEL_LABELS[release.channel] ?? release.channel}</Badge>
        </CardTitle>
        <StatusBadge tone={lifecycleTone(release.status)}>
          {LIFECYCLE_LABELS[release.status] ?? release.status}
        </StatusBadge>
      </CardHeader>
      <CardContent className='flex flex-col gap-3 p-4'>
        <div className='space-y-1.5 text-sm'>
          <p className='flex items-center justify-between'>
            <span className='text-muted-foreground'>Version</span>
            <span className='font-medium tabular-nums'>v{release.version}</span>
          </p>
          <p className='flex items-center justify-between gap-2'>
            <span className='text-muted-foreground'>Digest</span>
            <DigestTag value={release.digest} />
          </p>
          <p className='flex items-center justify-between'>
            <span className='text-muted-foreground'>Bound Hosts</span>
            <span className='tabular-nums'>{release.boundHosts}</span>
          </p>
          <p className='flex items-center justify-between'>
            <span className='text-muted-foreground'>Released By / At</span>
            <span>
              {release.releasedBy} · {formatDateTime(release.releasedAt)}
            </span>
          </p>
        </div>
        <div className='flex items-center gap-2'>
          <RiskConfirmDialog
            trigger={<Button variant='destructive' size='sm'>Revoke</Button>}
            title={`Revoke Release ${release.id}`}
            impact={`影响 ${release.boundHosts} 个 Host 的 Namespace Binding；使用该 Release 的 Task 将拒绝新建`}
            irreversibility='撤销后不可恢复，只能发布新版本替换'
            currentRevision={`v${release.version} · ${release.channel}`}
            actionLabel='确认撤销'
            onConfirm={() => {
              // 演示操作
            }}
          />
          <RiskConfirmDialog
            trigger={<Button variant='outline' size='sm'>Promote</Button>}
            title={`Promote Release ${release.id}`}
            impact={`将 ${CHANNEL_LABELS[release.channel] ?? release.channel} 渠道的 v${release.version} 提升为 stable，全量 Binding 生效`}
            irreversibility='提升立即生效，回滚需发布 rollback Rollout'
            currentRevision={`v${release.version} · ${release.channel}`}
            targetRevision='stable'
            actionLabel='确认提升'
            onConfirm={() => {
              // 演示操作
            }}
          />
        </div>
      </CardContent>
    </Card>
  );
}
