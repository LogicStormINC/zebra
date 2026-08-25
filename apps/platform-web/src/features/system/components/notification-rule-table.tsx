'use client';

import { Badge } from '@/components/ui/badge';
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
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Icons } from '@/components/icons';
import type { NotificationRule } from '@/lib/platform/types';
import { useState } from 'react';
import { toast } from 'sonner';

const CHANNEL_META: Record<NotificationRule['channel'], { label: string; tone: 'running' | 'waiting' | 'draft' }> = {
  webhook: { label: 'Webhook', tone: 'running' },
  email: { label: 'Email', tone: 'waiting' },
  slack: { label: 'Slack', tone: 'draft' }
};

/** Notification Rule 列表（PRD 14.5）：平台事件到通知渠道的路由。 */
export function NotificationRuleTable({ rules }: { rules: NotificationRule[] }) {
  const [localRules, setLocalRules] = useState<NotificationRule[]>(rules);
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [event, setEvent] = useState('');
  const [channel, setChannel] = useState<NotificationRule['channel']>('webhook');
  const [target, setTarget] = useState('');

  const enabledOf = (rule: NotificationRule) => overrides[rule.id] ?? rule.enabled;

  const toggle = (rule: NotificationRule, next: boolean) => {
    setOverrides((prev) => ({ ...prev, [rule.id]: next }));
    toast.success('通知规则已更新（演示）', {
      description: `${rule.event} · ${CHANNEL_META[rule.channel].label} → ${next ? '启用' : '停用'}`
    });
  };

  const submitCreate = () => {
    const trimmedEvent = event.trim();
    const trimmedTarget = target.trim();
    if (!/^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/.test(trimmedEvent)) {
      toast.error('Event 需要是 a.b 形式的事件标识，例如 budget.warning_threshold');
      return;
    }
    if (trimmedTarget.length < 3) {
      toast.error('请输入有效的通知目标（Webhook URL、邮箱或频道名）');
      return;
    }
    const id = `nr_local_${localRules.length + 1}`;
    setLocalRules((prev) => [
      { id, event: trimmedEvent, channel, target: trimmedTarget, enabled: true },
      ...prev
    ]);
    toast.success('通知规则已创建（演示）', {
      description: `${trimmedEvent} → ${CHANNEL_META[channel].label} ${trimmedTarget}`
    });
    setEvent('');
    setTarget('');
    setChannel('webhook');
    setCreateOpen(false);
  };

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex items-center justify-between gap-2'>
        <span className='text-muted-foreground text-xs'>{localRules.length} 条规则</span>
        <Button size='sm' onClick={() => setCreateOpen(true)}>
          <Icons.plusCircle />
          新建规则
        </Button>
      </div>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted sticky top-0'>
            <TableRow>
              <TableHead>Event</TableHead>
              <TableHead>Channel</TableHead>
              <TableHead className='min-w-64'>Target</TableHead>
              <TableHead>Enabled</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {localRules.map((rule) => (
              <TableRow key={rule.id}>
                <TableCell>
                  <code className='bg-muted rounded px-1.5 py-0.5 font-mono text-xs'>{rule.event}</code>
                </TableCell>
                <TableCell>
                  <Badge variant='secondary' className='text-xs'>
                    {CHANNEL_META[rule.channel].label}
                  </Badge>
                </TableCell>
                <TableCell>
                  <span className='font-mono text-xs break-all'>{rule.target}</span>
                </TableCell>
                <TableCell>
                  <div className='flex items-center gap-2'>
                    <Switch
                      checked={enabledOf(rule)}
                      onCheckedChange={(checked) => toggle(rule, checked === true)}
                      aria-label={`切换 ${rule.event}`}
                    />
                    <span
                      className={
                        enabledOf(rule)
                          ? 'text-emerald-600 dark:text-emerald-400 text-xs font-medium'
                          : 'text-muted-foreground text-xs'
                      }
                    >
                      {enabledOf(rule) ? '启用' : '停用'}
                    </span>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建通知规则</DialogTitle>
            <DialogDescription>选择平台事件并配置通知渠道与目标。</DialogDescription>
          </DialogHeader>
          <div className='space-y-1.5'>
            <Label htmlFor='rule-event'>Event</Label>
            <Input
              id='rule-event'
              placeholder='budget.warning_threshold'
              value={event}
              onChange={(eventInput) => setEvent(eventInput.target.value)}
            />
          </div>
          <div className='space-y-1.5'>
            <Label>Channel</Label>
            <Select value={channel} onValueChange={(value) => setChannel(value as NotificationRule['channel'])}>
              <SelectTrigger className='w-full'>
                <SelectValue placeholder='渠道' />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {(Object.keys(CHANNEL_META) as NotificationRule['channel'][]).map((option) => (
                    <SelectItem key={option} value={option}>
                      {CHANNEL_META[option].label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1.5'>
            <Label htmlFor='rule-target'>Target</Label>
            <Input
              id='rule-target'
              placeholder='https://hooks.example.com/… 或 #channel 或邮箱'
              value={target}
              onChange={(eventInput) => setTarget(eventInput.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant='outline' size='sm' onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button size='sm' onClick={submitCreate}>
              创建规则
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
