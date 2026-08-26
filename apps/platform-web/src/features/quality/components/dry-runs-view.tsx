'use client';

import Link from 'next/link';
import { useState } from 'react';
import { toast } from 'sonner';

import { Alert, AlertDescription } from '@/components/ui/alert';
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { EmptyState } from '@/components/platform/empty-state';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { AgentRelease, BackendManifest, DryRun, FrontendProfile } from '@/lib/platform/types';

const RESULT_LABELS: Record<DryRun['result'], string> = {
  passed: '通过',
  failed: '失败',
  running: '运行中'
};

/** Dry Run 列表 + 新建表单（PRD 17）。 */
export function DryRunsView({
  dryRuns,
  agentReleases,
  manifests,
  frontendProfiles
}: {
  dryRuns: DryRun[];
  agentReleases: AgentRelease[];
  manifests: BackendManifest[];
  frontendProfiles: FrontendProfile[];
}) {
  const [createOpen, setCreateOpen] = useState(false);
  const [releaseId, setReleaseId] = useState(agentReleases[0]?.id ?? '');
  const [manifestId, setManifestId] = useState(manifests[0]?.id ?? '');
  const [profileId, setProfileId] = useState(frontendProfiles[0]?.id ?? '');
  const [resourceRef, setResourceRef] = useState('');

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex items-center justify-between gap-2'>
        <p className='text-muted-foreground text-sm'>
          Dry Run 使用独立 namespace 或测试标记执行真实链路验证，禁止写入 Production 业务数据。
        </p>
        <Button size='sm' onClick={() => setCreateOpen(true)}>
          新建 Dry Run
        </Button>
      </div>

      {dryRuns.length === 0 ? (
        <EmptyState
          title='暂无 Dry Run'
          description='创建 Dry Run 在隔离 namespace 中验证 Agent Release 的读写链路'
          icon='dryRun'
        />
      ) : (
        <div className='overflow-x-auto rounded-lg border'>
          <Table>
            <TableHeader className='bg-muted'>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Task</TableHead>
                <TableHead>Host</TableHead>
                <TableHead>Agent Release</TableHead>
                <TableHead>Namespace</TableHead>
                <TableHead>Result</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {dryRuns.map((dryRun) => (
                <TableRow key={dryRun.id}>
                  <TableCell className='font-mono text-xs'>{dryRun.id}</TableCell>
                  <TableCell>
                    <Link
                      href={`/runtime/tasks/${dryRun.taskId}`}
                      className='text-primary hover:underline font-mono text-xs'
                    >
                      {dryRun.taskId}
                    </Link>
                  </TableCell>
                  <TableCell className='text-sm'>{dryRun.hostAppId}</TableCell>
                  <TableCell className='font-mono text-xs'>{dryRun.agentReleaseId}</TableCell>
                  <TableCell className='font-mono text-xs'>{dryRun.namespace}</TableCell>
                  <TableCell>
                    <StatusBadge tone={lifecycleTone(dryRun.result)} withDot={false}>
                      {RESULT_LABELS[dryRun.result]}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className='max-w-72 truncate text-xs'>{dryRun.summary}</TableCell>
                  <TableCell className='text-muted-foreground text-xs'>
                    {formatDateTime(dryRun.createdAt)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className='max-w-md'>
          <DialogHeader>
            <DialogTitle>新建 Dry Run</DialogTitle>
            <DialogDescription>
              选择要验证的发布组合与测试资源，Dry Run 在隔离环境中执行。
            </DialogDescription>
          </DialogHeader>
          <div className='space-y-3'>
            <div className='space-y-1.5'>
              <span className='text-sm font-medium'>Agent Release</span>
              <Select value={releaseId} onValueChange={(value) => value && setReleaseId(value)}>
                <SelectTrigger className='w-full' aria-label='选择 Agent Release'>
                  <SelectValue placeholder='选择 Agent Release' />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {agentReleases.map((release) => (
                      <SelectItem key={release.id} value={release.id}>
                        {release.definitionName} v{release.version}（{release.channel}）
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <div className='space-y-1.5'>
              <span className='text-sm font-medium'>Backend Manifest</span>
              <Select value={manifestId} onValueChange={(value) => value && setManifestId(value)}>
                <SelectTrigger className='w-full' aria-label='选择 Backend Manifest'>
                  <SelectValue placeholder='选择 Backend Manifest' />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {manifests.map((manifest) => (
                      <SelectItem key={manifest.id} value={manifest.id}>
                        {manifest.id}（rev {manifest.revision}）
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <div className='space-y-1.5'>
              <span className='text-sm font-medium'>Frontend Profile</span>
              <Select value={profileId} onValueChange={(value) => value && setProfileId(value)}>
                <SelectTrigger className='w-full' aria-label='选择 Frontend Profile'>
                  <SelectValue placeholder='选择 Frontend Profile' />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {frontendProfiles.map((profile) => (
                      <SelectItem key={profile.id} value={profile.id}>
                        {profile.frontendAppId}（rev {profile.revision}）
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <div className='space-y-1.5'>
              <span className='text-sm font-medium'>测试 Resource Ref</span>
              <Input
                value={resourceRef}
                onChange={(event) => setResourceRef(event.target.value)}
                placeholder='例如 test-resource:trench-dry-run-01'
              />
            </div>
            <Alert variant='destructive'>
              <span className='text-xs font-medium'>数据边界</span>
              <AlertDescription className='text-xs'>
                Dry Run 使用独立 namespace 或测试标记，禁止写入 Production 业务数据。
              </AlertDescription>
            </Alert>
          </div>
          <DialogFooter>
            <Button variant='outline' size='sm' onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button
              size='sm'
              disabled={!releaseId || !manifestId || !resourceRef.trim()}
              onClick={() => {
                setCreateOpen(false);
                toast.success('Dry Run 已创建', {
                  description: `release=${releaseId} manifest=${manifestId} profile=${profileId} ref=${resourceRef.trim()}（演示）`
                });
              }}
            >
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
