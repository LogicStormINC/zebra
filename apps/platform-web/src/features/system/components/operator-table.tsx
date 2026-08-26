'use client';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { StatusBadge } from '@/components/platform/status-badge';
import { Icons } from '@/components/icons';
import { relativeTime } from '@/lib/platform/format';
import type { OperatorRecord } from '@/lib/platform/types';
import { useState } from 'react';
import { toast } from 'sonner';

const STATUS_META: Record<OperatorRecord['status'], { label: string; tone: 'success' | 'waiting' | 'failure' }> = {
  active: { label: '活跃', tone: 'success' },
  invited: { label: '已邀请', tone: 'waiting' },
  suspended: { label: '已停用', tone: 'failure' }
};

const ROLE_OPTIONS = [
  'Platform Owner',
  'Platform Admin',
  'Integration Engineer',
  'Agent Publisher',
  'Runtime Operator',
  'Security Auditor',
  'Business Observer',
  'Support Engineer'
];

/** Operator 与角色注册表（PRD 14.2）：当前阶段仅维护角色映射，服务端保留最终授权。 */
export function OperatorTable({ operators }: { operators: OperatorRecord[] }) {
  const [inviteOpen, setInviteOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [roles, setRoles] = useState<string[]>([]);

  const toggleRole = (role: string, checked: boolean) => {
    setRoles((prev) => (checked ? [...prev, role] : prev.filter((item) => item !== role)));
  };

  const submitInvite = () => {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      toast.error('请输入有效的 Email 地址');
      return;
    }
    if (roles.length === 0) {
      toast.error('请至少选择一个角色');
      return;
    }
    toast.success('邀请已发送（演示）', {
      description: `${email.trim()} · ${roles.join(' / ')}；角色注册表变更将写入 Audit Log`
    });
    setEmail('');
    setRoles([]);
    setInviteOpen(false);
  };

  return (
    <div className='flex flex-col gap-4'>
      <Alert>
        <Icons.lock />
        <AlertTitle>认证现状说明</AlertTitle>
        <AlertDescription>
          平台当前阶段未启用登录认证（OIDC 待接入），此页仅维护 Operator
          角色注册表；服务端保留最终授权。
        </AlertDescription>
      </Alert>

      <div className='flex items-center justify-between gap-2'>
        <span className='text-muted-foreground text-xs'>{operators.length} 位 Operator</span>
        <Button size='sm' onClick={() => setInviteOpen(true)}>
          <Icons.plusCircle />
          邀请 Operator
        </Button>
      </div>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted sticky top-0'>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Roles</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last Active</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {operators.map((operator) => (
              <TableRow key={operator.id}>
                <TableCell className='font-medium'>
                  <span className='flex items-center gap-2'>
                    <Icons.user className='text-muted-foreground size-3.5' />
                    {operator.name}
                  </span>
                </TableCell>
                <TableCell>
                  <span className='font-mono text-xs'>{operator.email}</span>
                </TableCell>
                <TableCell>
                  <div className='flex max-w-md flex-wrap gap-1'>
                    {operator.roles.map((role) => (
                      <Badge key={role} variant='secondary' className='px-1.5 text-[11px]'>
                        {role}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <StatusBadge tone={STATUS_META[operator.status].tone}>
                    {STATUS_META[operator.status].label}
                  </StatusBadge>
                </TableCell>
                <TableCell className='text-muted-foreground text-xs whitespace-nowrap'>
                  {relativeTime(operator.lastActiveAt)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle>邀请 Operator</DialogTitle>
            <DialogDescription>
              邀请发出后角色注册表即刻生效；OIDC 接入前登录态由服务端最终授权决定。
            </DialogDescription>
          </DialogHeader>
          <div className='space-y-1.5'>
            <Label htmlFor='invite-email'>Email</Label>
            <Input
              id='invite-email'
              type='email'
              placeholder='operator@example.com'
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div className='space-y-2'>
            <Label>角色（可多选）</Label>
            <div className='grid grid-cols-2 gap-2'>
              {ROLE_OPTIONS.map((role) => (
                <label key={role} className='flex cursor-pointer items-center gap-2 text-sm'>
                  <Checkbox
                    checked={roles.includes(role)}
                    onCheckedChange={(checked) => toggleRole(role, checked === true)}
                  />
                  {role}
                </label>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button variant='outline' size='sm' onClick={() => setInviteOpen(false)}>
              取消
            </Button>
            <Button size='sm' onClick={submitInvite}>
              发送邀请
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
