'use client';

import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/platform/status-badge';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { Icons } from '@/components/icons';

const CHECKLIST = [
  { name: 'Schema Validation', priority: 'P0', status: 'passed' },
  { name: 'Backend Conformance', priority: 'P0', status: 'passed' },
  { name: 'Frontend Conformance', priority: 'P0', status: 'passed' },
  { name: 'Dry Run', priority: 'P0', status: 'passed' },
  { name: 'Binding Preview', priority: 'P1', status: 'pending' },
  { name: 'Security Review', priority: 'P1', status: 'pending' },
  { name: 'Canary Plan', priority: 'P1', status: 'pending' }
] as const;

/** Step 7 验证与发布（PRD 10.3）：发布前检查清单 + Production 发布（高风险确认）。 */
export function OnboardingStepPublish({
  hostName,
  onPublished
}: {
  hostName: string;
  onPublished: () => void;
}) {
  const p0AllPassed = CHECKLIST.filter((item) => item.priority === 'P0').every(
    (item) => item.status === 'passed'
  );
  const passedCount = CHECKLIST.filter((item) => item.status === 'passed').length;

  return (
    <div className='flex flex-col gap-4'>
      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>
            发布前检查清单（{passedCount}/{CHECKLIST.length} 通过）
          </CardTitle>
        </CardHeader>
        <CardContent className='divide-y p-0'>
          {CHECKLIST.map((item) => (
            <div key={item.name} className='flex items-center justify-between gap-3 px-4 py-2.5'>
              <div className='flex items-center gap-2'>
                {item.status === 'passed' ? (
                  <Icons.circleCheck className='text-emerald-600 size-4' />
                ) : (
                  <Icons.clock className='text-muted-foreground size-4' />
                )}
                <span className='text-sm font-medium'>{item.name}</span>
                <span className='text-muted-foreground text-xs'>{item.priority}</span>
              </div>
              <StatusBadge tone={item.status === 'passed' ? 'success' : 'waiting'} withDot={false}>
                {item.status === 'passed' ? '已通过' : '待检查'}
              </StatusBadge>
            </div>
          ))}
        </CardContent>
      </Card>

      {!p0AllPassed && (
        <Alert variant='destructive'>
          <Icons.warning />
          <AlertTitle>P0 检查未全部通过</AlertTitle>
          <AlertDescription>
            Schema / Conformance / Dry Run 全部通过后才能发布到 Production。
          </AlertDescription>
        </Alert>
      )}

      <div className='flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4'>
        <div>
          <p className='text-sm font-medium'>发布 {hostName || '该 Host'} 到 Production</p>
          <p className='text-muted-foreground text-xs'>
            发布后将创建 Trust / Connector / Manifest / Frontend Profile 的首个 Revision，并生成
            Namespace Binding。
          </p>
        </div>
        {p0AllPassed ? (
          <RiskConfirmDialog
            trigger={
              <Button>
                <Icons.sparkles data-icon='inline-start' />
                发布到 Production
              </Button>
            }
            title='发布 Host 到 Production'
            impact='创建各资产首个 published Revision；Host 进入 active 状态并开始接收 Task。'
            irreversibility='发布后 App ID 与首个 Revision 不可修改；回退需要通过 Rollout 流程。'
            targetRevision='首个 published Revision'
            actionLabel='确认发布'
            onConfirm={(reason) => {
              toast.success('发布请求已提交（演示）', { description: `审计原因：${reason}` });
              onPublished();
            }}
          />
        ) : (
          <Button disabled>
            <Icons.sparkles data-icon='inline-start' />
            发布到 Production
          </Button>
        )}
      </div>
    </div>
  );
}
