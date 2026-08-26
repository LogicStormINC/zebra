'use client';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { JsonBlock } from '@/components/platform/json-block';
import { StatusBadge } from '@/components/platform/status-badge';
import type { FrontendProfile, MountedCapabilitySnapshot } from '@/lib/platform/types';
import { DRIFT_LABELS, driftTone } from './labels';

/** 查看 Snapshot：只读 JSON（PRD 25.4：禁止渲染未净化 HTML）。 */
export function SnapshotJsonDialog({
  snapshot,
  open,
  onOpenChange
}: {
  snapshot: MountedCapabilitySnapshot | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[85vh] max-w-xl overflow-y-auto'>
        {snapshot && (
          <>
            <DialogHeader>
              <DialogTitle>Mounted Snapshot</DialogTitle>
              <DialogDescription className='font-mono text-xs'>
                {snapshot.mountedSnapshotDigest}
              </DialogDescription>
            </DialogHeader>
            <JsonBlock value={snapshot} maxHeight={420} />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DiffRow({
  label,
  expected,
  actual,
  matched
}: {
  label: string;
  expected: string;
  actual: string;
  matched: boolean;
}) {
  return (
    <div className='grid grid-cols-[7rem_1fr_1fr] items-start gap-2 border-b px-3 py-2 text-xs last:border-0'>
      <span className='text-muted-foreground font-medium'>{label}</span>
      <span className='font-mono break-all'>{expected}</span>
      <span className='flex flex-col gap-1'>
        <span className='font-mono break-all'>{actual}</span>
        <StatusBadge tone={matched ? 'success' : 'failure'} withDot={false}>
          {matched ? '一致' : '不一致'}
        </StatusBadge>
      </span>
    </div>
  );
}

/** 比较 Published Profile：快照 vs 当前发布 Profile 的关键字段 diff。 */
export function SnapshotDiffDialog({
  snapshot,
  profile,
  open,
  onOpenChange
}: {
  snapshot: MountedCapabilitySnapshot | null;
  profile: FrontendProfile | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[85vh] max-w-2xl overflow-y-auto'>
        {snapshot && (
          <>
            <DialogHeader>
              <DialogTitle>快照 vs Published Profile</DialogTitle>
              <DialogDescription>
                会话 <span className='font-mono'>{snapshot.clientSessionId}</span> 的挂载快照与当前发布
                Profile 的比对；{profile ? `基准 ${profile.id} rev ${profile.revision}` : '未找到匹配的已发布 Profile'}。
              </DialogDescription>
            </DialogHeader>

            {profile ? (
              <div className='rounded-lg border'>
                <div className='grid grid-cols-[7rem_1fr_1fr] gap-2 border-b bg-muted px-3 py-2 text-xs font-medium'>
                  <span>字段</span>
                  <span>Published Profile</span>
                  <span>Mounted Snapshot</span>
                </div>
                <DiffRow
                  label='Profile Digest'
                  expected={profile.digest.slice(0, 16)}
                  actual={snapshot.profileDigest.slice(0, 16)}
                  matched={snapshot.profileDigest.slice(0, 8) === profile.digest.slice(0, 8)}
                />
                <DiffRow
                  label='Build'
                  expected={profile.buildId}
                  actual={snapshot.frontendBuild}
                  matched={snapshot.frontendBuild === profile.buildId}
                />
                <DiffRow
                  label='Readables'
                  expected={profile.readables.map((item) => item.name).join(', ') || '—'}
                  actual={snapshot.mountedReadables.join(', ') || '—'}
                  matched={
                    profile.readables.length === snapshot.mountedReadables.length &&
                    profile.readables.every((item) => snapshot.mountedReadables.includes(item.name))
                  }
                />
                <DiffRow
                  label='Actions'
                  expected={profile.actions.map((item) => item.name).join(', ') || '—'}
                  actual={snapshot.mountedActions.join(', ') || '—'}
                  matched={
                    profile.actions.length === snapshot.mountedActions.length &&
                    profile.actions.every((item) => snapshot.mountedActions.includes(item.name))
                  }
                />
                <DiffRow
                  label='Components'
                  expected={profile.components.join(', ') || '—'}
                  actual={snapshot.mountedComponents.join(', ') || '—'}
                  matched={
                    profile.components.length === snapshot.mountedComponents.length &&
                    profile.components.every((item) => snapshot.mountedComponents.includes(item))
                  }
                />
                <div className='flex items-center justify-between px-3 py-2 text-xs'>
                  <span className='text-muted-foreground'>Drift 判定</span>
                  <StatusBadge tone={driftTone(snapshot.driftStatus)}>
                    {DRIFT_LABELS[snapshot.driftStatus]}
                  </StatusBadge>
                </div>
              </div>
            ) : (
              <p className='text-muted-foreground text-sm'>
                没有找到 Digest 前缀匹配的已发布 Profile，快照可能来自旧版本或未知来源。
              </p>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
