'use client';
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
import { DataList } from '@/components/platform/data-list';
import { DigestTag } from '@/components/platform/mono-id';
import { Icons } from '@/components/icons';
import { formatNumber } from '@/lib/platform/format';
import type { TaskDetailData } from './task-detail-data';
import { TASK_BUDGET_TOKENS, TASK_BUDGET_USD } from './task-detail-data';

/** Binding Tab（PRD 18.12）：Task 创建时冻结的不可变快照卡片墙。 */
export function TaskBindingTab({ data }: { data: TaskDetailData }) {
  const { task, release, definition, host, manifest, frontendProfile, clientRunBindings } = data;
  const binding = clientRunBindings[0];

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex items-center justify-between gap-2'>
        <p className='text-muted-foreground text-xs'>
          以下快照在 Task 创建时冻结，运行期不可变；与当前已发布版本的差异只提示、不热更新。
        </p>
        <BindingDriftDialog data={data} />
      </div>

      <div className='grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3'>
        <SnapshotCard title='AgentDefinition Snapshot Digest'>
          {release ? <DigestTag value={release.digest} /> : '—'}
          {definition && (
            <p className='text-muted-foreground mt-1 text-xs'>
              {definition.name} · v{release?.version ?? definition.latestVersion}
            </p>
          )}
        </SnapshotCard>

        <SnapshotCard title='Agent Capability Ceiling'>
          <div className='flex flex-wrap gap-1.5'>
            {(definition?.capabilityCeiling ?? []).map((capability) => (
              <Badge key={capability} variant='secondary' className='font-mono text-xs'>
                {capability}
              </Badge>
            ))}
          </div>
        </SnapshotCard>

        <SnapshotCard title='Host Capability Snapshot'>
          {host ? (
            <span className='text-sm'>
              {host.name} · manifest{' '}
              {manifest ? <DigestTag value={manifest.digest} /> : '—'}
            </span>
          ) : (
            <span className='text-muted-foreground text-sm'>未找到 Host 快照</span>
          )}
        </SnapshotCard>

        <SnapshotCard title='Connector Profile Revision'>
          {host?.connectorRevision ? `rev ${host.connectorRevision}` : '—'}
        </SnapshotCard>

        <SnapshotCard title='Backend Manifest Digest'>
          {manifest ? <DigestTag value={manifest.digest} /> : '—'}
        </SnapshotCard>

        <SnapshotCard title='Frontend Profile Digest'>
          {frontendProfile ? (
            <span className='flex flex-col items-start gap-1'>
              <DigestTag value={frontendProfile.digest} />
              <span className='text-muted-foreground text-xs'>
                {frontendProfile.id} · rev {frontendProfile.revision}
              </span>
            </span>
          ) : (
            <span className='text-muted-foreground text-sm'>未绑定前端</span>
          )}
        </SnapshotCard>

        <SnapshotCard title='Client Run Binding'>
          {binding ? (
            <span className='flex flex-col items-start gap-1'>
              <DigestTag value={binding.snapshotDigest} />
              <span className='text-muted-foreground text-xs'>
                {binding.id} · {binding.status}
              </span>
            </span>
          ) : (
            <span className='text-muted-foreground text-sm'>无</span>
          )}
        </SnapshotCard>

        <SnapshotCard title='Zebra Policy Digest'>
          <DigestTag value={`pol_zebra_effective_${task.namespace.replace(/[^a-z0-9]/gi, '')}_${task.agentReleaseId.slice(-6)}`} />
          <p className='text-muted-foreground mt-1 text-xs'>
            平台侧合成策略（capability × network × approval 交集）
          </p>
        </SnapshotCard>

        <SnapshotCard title='Effective Capabilities'>
          <div className='flex flex-wrap gap-1.5'>
            {(definition?.capabilityCeiling ?? []).map((capability) => (
              <Badge key={capability} variant='outline' className='font-mono text-xs'>
                {capability}
              </Badge>
            ))}
          </div>
        </SnapshotCard>

        <SnapshotCard title='Effective Limits'>
          <DataList
            columns={2}
            items={[
              { label: 'Model Tokens', value: formatNumber(TASK_BUDGET_TOKENS) },
              { label: 'Cost', value: `$${TASK_BUDGET_USD.toFixed(2)}` },
              { label: 'Max Subagents', value: '8' },
              { label: 'Client Actions', value: '200 / run' }
            ]}
          />
        </SnapshotCard>

        <SnapshotCard title='Resource Refs'>
          <DataList
            columns={2}
            items={[
              { label: 'Host', value: task.hostAppId },
              { label: 'Namespace', value: <span className='font-mono text-xs'>{task.namespace}</span> },
              { label: 'Agent Release', value: task.agentReleaseId },
              { label: 'Orchestration', value: task.orchestrationRunRef ?? '—' }
            ]}
          />
        </SnapshotCard>
      </div>
    </div>
  );
}

function SnapshotCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className='py-0'>
      <CardHeader className='border-b px-4 py-2.5'>
        <CardTitle className='text-xs font-medium'>{title}</CardTitle>
      </CardHeader>
      <CardContent className='p-4'>{children}</CardContent>
    </Card>
  );
}

function BindingDriftDialog({ data }: { data: TaskDetailData }) {
  const { task, release, definition } = data;
  const drifted =
    definition?.publishedReleaseId !== undefined &&
    release !== undefined &&
    definition.publishedReleaseId !== release.id;

  return (
    <Dialog>
      <DialogTrigger render={<Button variant='outline' size='sm' />}>
        <Icons.reconciliation className='size-4' />
        比较当前已发布版本
      </DialogTrigger>
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle>Binding 漂移检查</DialogTitle>
          <DialogDescription>
            Task 快照 vs 该 Definition 当前已发布 Release（静态比较，不会修改 Task）
          </DialogDescription>
        </DialogHeader>
        <div className='space-y-3 text-sm'>
          <div className='bg-muted/40 rounded-lg border p-3'>
            <p className='text-muted-foreground text-xs'>Task 快照</p>
            <p className='mt-1 font-mono text-xs'>
              {task.agentReleaseId}
              {release ? ` · v${release.version} · ${release.channel}` : ''}
            </p>
          </div>
          <div className='bg-muted/40 rounded-lg border p-3'>
            <p className='text-muted-foreground text-xs'>当前已发布</p>
            <p className='mt-1 font-mono text-xs'>
              {definition?.publishedReleaseId ?? '无已发布 Release'}
            </p>
          </div>
          {drifted ? (
            <div className='border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-400 rounded-lg border p-3'>
              <p className='font-medium'>检测到漂移</p>
              <p className='mt-1 text-xs'>
                Definition 已发布新 Release（{definition?.publishedReleaseId}）；本 Task 继续使用快照版本执行，
                新 Task 将使用新 Release。如需切换请取消后重建。
              </p>
            </div>
          ) : (
            <p className='flex items-center gap-2'>
              <Icons.check className='text-emerald-600 size-4' />
              无漂移：Task 快照与当前已发布版本一致。
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
