'use client';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from '@/components/ui/alert-dialog';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useState } from 'react';
import { toast } from 'sonner';
import { environmentLabel, useEnvironmentStore } from '@/lib/platform/environment-store';

/**
 * 高风险操作确认弹窗（PRD 6.4）：
 * 必须显示影响范围、不可逆性、当前/目标 revision，并要求填写审计原因。
 * 触发按钮通过 children 传入；也可通过 open/onOpenChange 受控打开
 * （例如从表格行操作菜单中触发）。
 * 弹窗信息区固定展示当前环境上下文（PRD 8.2），
 * Production 环境下红色加粗并要求二次确认影响范围。
 */
export function RiskConfirmDialog({
  trigger,
  title,
  impact,
  irreversibility,
  currentRevision,
  targetRevision,
  actionLabel = '确认执行',
  requireReason = true,
  open: controlledOpen,
  onOpenChange,
  onConfirm
}: {
  trigger?: React.ReactElement;
  title: string;
  impact: string;
  irreversibility?: string;
  currentRevision?: string;
  targetRevision?: string;
  actionLabel?: string;
  requireReason?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState('');
  const [internalOpen, setInternalOpen] = useState(false);
  const environment = useEnvironmentStore((state) => state.environment);
  const isProduction = environment === 'production';
  const open = controlledOpen ?? internalOpen;
  const setOpen = (next: boolean) => {
    onOpenChange?.(next);
    setInternalOpen(next);
  };
  const reasonValid = !requireReason || reason.trim().length >= 4;

  const handleConfirm = () => {
    onConfirm(reason.trim());
    setReason('');
    setOpen(false);
    toast.success('操作已提交，审计记录已写入', {
      description: `${title}`
    });
  };

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      {trigger && <AlertDialogTrigger render={trigger} />}
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>高风险操作：{title}</AlertDialogTitle>
          <AlertDialogDescription>请确认影响范围与审计原因后继续。</AlertDialogDescription>
        </AlertDialogHeader>
        <div className='text-muted-foreground space-y-2 text-sm'>
          <p className={isProduction ? 'text-destructive font-bold' : undefined}>
            当前环境：{environmentLabel(environment)}
            {isProduction && ' —— Production 环境写操作，请二次确认影响范围'}
          </p>
          <p>
            <span className='text-destructive font-medium'>影响范围：</span>
            {impact}
          </p>
          {irreversibility && (
            <p>
              <span className='font-medium'>不可逆性：</span>
              {irreversibility}
            </p>
          )}
          {(currentRevision || targetRevision) && (
            <p className='font-mono text-xs'>
              {currentRevision && <span>当前：{currentRevision} </span>}
              {targetRevision && <span>目标：{targetRevision}</span>}
            </p>
          )}
        </div>
        <div className='space-y-1.5'>
          <Label htmlFor='risk-reason'>审计原因{requireReason ? '（必填）' : '（选填）'}</Label>
          <Textarea
            id='risk-reason'
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder='说明本次操作的业务原因，将写入 Audit Log'
            rows={2}
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction
            disabled={!reasonValid}
            onClick={(event) => {
              event.preventDefault();
              handleConfirm();
            }}
          >
            {actionLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
