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
import { DataList } from '@/components/platform/data-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime, relativeTime } from '@/lib/platform/format';
import type { SecurityFinding } from '@/lib/platform/types';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

const SEVERITY_META: Record<
  SecurityFinding['severity'],
  { label: string; tone: 'failure' | 'uncertain' | 'warning' | 'draft' }
> = {
  critical: { label: 'Critical 严重', tone: 'failure' },
  high: { label: 'High 高', tone: 'uncertain' },
  medium: { label: 'Medium 中', tone: 'warning' },
  low: { label: 'Low 低', tone: 'draft' }
};

const STATUS_META: Record<
  SecurityFinding['status'],
  { label: string; tone: 'warning' | 'waiting' | 'running' | 'success' }
> = {
  open: { label: '待处理', tone: 'warning' },
  acknowledged: { label: '已确认', tone: 'waiting' },
  mitigated: { label: '已缓解', tone: 'running' },
  resolved: { label: '已解决', tone: 'success' }
};

const SEVERITY_ORDER: SecurityFinding['severity'][] = ['critical', 'high', 'medium', 'low'];

const TRANSITIONS: Record<SecurityFinding['status'], { key: SecurityFinding['status']; label: string }[]> = {
  open: [{ key: 'acknowledged', label: 'Acknowledge 确认' }],
  acknowledged: [{ key: 'mitigated', label: 'Mitigate 缓解' }],
  mitigated: [{ key: 'resolved', label: 'Resolve 解决' }],
  resolved: []
};

export function SecurityFindings({ findings }: { findings: SecurityFinding[] }) {
  const [severityFilter, setSeverityFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [overrides, setOverrides] = useState<Record<string, SecurityFinding['status']>>({});
  const [selected, setSelected] = useState<SecurityFinding | null>(null);

  const statusOf = (finding: SecurityFinding): SecurityFinding['status'] =>
    overrides[finding.id] ?? finding.status;

  const filtered = useMemo(
    () =>
      findings
        .filter(
          (finding) =>
            (severityFilter === 'all' || finding.severity === severityFilter) &&
            (statusFilter === 'all' || statusOf(finding) === statusFilter)
        )
        .toSorted(
          (a, b) =>
            SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity) ||
            b.detectedAt.localeCompare(a.detectedAt)
        ),
    [findings, severityFilter, statusFilter, overrides]
  );

  const transition = (finding: SecurityFinding, next: SecurityFinding['status']) => {
    setOverrides((prev) => ({ ...prev, [finding.id]: next }));
    toast.success(`状态流转已提交（演示）`, {
      description: `${finding.id} → ${STATUS_META[next].label}；流转与操作者将写入 Audit Log`
    });
  };

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <Select value={severityFilter} onValueChange={(value) => setSeverityFilter(value ?? 'all')}>
          <SelectTrigger size='sm' className='w-40'>
            <SelectValue placeholder='Severity' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部 Severity</SelectItem>
              {SEVERITY_ORDER.map((severity) => (
                <SelectItem key={severity} value={severity}>
                  {SEVERITY_META[severity].label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value ?? 'all')}>
          <SelectTrigger size='sm' className='w-36'>
            <SelectValue placeholder='Status' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部状态</SelectItem>
              {(Object.keys(STATUS_META) as SecurityFinding['status'][]).map((status) => (
                <SelectItem key={status} value={status}>
                  {STATUS_META[status].label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <span className='text-muted-foreground text-xs'>{filtered.length} 条 Finding</span>
      </div>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted sticky top-0'>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Resource</TableHead>
              <TableHead className='min-w-64'>Description</TableHead>
              <TableHead className='min-w-64'>Recommendation</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Detected At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((finding) => (
              <TableRow key={finding.id} className='cursor-pointer' onClick={() => setSelected(finding)}>
                <TableCell>
                  <StatusBadge tone={SEVERITY_META[finding.severity].tone}>
                    {SEVERITY_META[finding.severity].label}
                  </StatusBadge>
                </TableCell>
                <TableCell className='font-medium'>{finding.title}</TableCell>
                <TableCell>
                  <span className='font-mono text-xs'>{finding.resource}</span>
                </TableCell>
                <TableCell className='text-muted-foreground max-w-64 truncate text-xs'>
                  {finding.description}
                </TableCell>
                <TableCell className='text-muted-foreground max-w-64 truncate text-xs'>
                  {finding.recommendation}
                </TableCell>
                <TableCell>
                  <StatusBadge tone={STATUS_META[statusOf(finding)].tone}>
                    {STATUS_META[statusOf(finding)].label}
                  </StatusBadge>
                </TableCell>
                <TableCell className='text-muted-foreground text-xs whitespace-nowrap'>
                  {formatDateTime(finding.detectedAt)}
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className='text-muted-foreground h-24 text-center'>
                  没有匹配的 Security Finding
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className='max-h-[85vh] overflow-y-auto sm:max-w-xl'>
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className='flex flex-wrap items-center gap-2'>
                  {selected.title}
                  <StatusBadge tone={SEVERITY_META[selected.severity].tone}>
                    {SEVERITY_META[selected.severity].label}
                  </StatusBadge>
                  <StatusBadge tone={STATUS_META[statusOf(selected)].tone}>
                    {STATUS_META[statusOf(selected)].label}
                  </StatusBadge>
                </DialogTitle>
                <DialogDescription>Security Finding 详情与状态流转</DialogDescription>
              </DialogHeader>
              <DataList
                columns={2}
                items={[
                  { label: 'Finding ID', value: <span className='font-mono text-xs'>{selected.id}</span> },
                  { label: 'Resource', value: <span className='font-mono text-xs'>{selected.resource}</span> },
                  { label: 'Detected At', value: `${formatDateTime(selected.detectedAt)}（${relativeTime(selected.detectedAt)}）` },
                  { label: '当前状态', value: STATUS_META[statusOf(selected)].label }
                ]}
              />
              <div className='space-y-2 text-sm'>
                <p>
                  <span className='text-muted-foreground'>描述：</span>
                  {selected.description}
                </p>
                <p>
                  <span className='text-muted-foreground'>处置建议：</span>
                  {selected.recommendation}
                </p>
              </div>
              <DialogFooter className='items-center justify-between sm:justify-between'>
                <p className='text-muted-foreground text-xs'>状态流转将写入 Audit Log（含操作者与原因）。</p>
                <div className='flex items-center gap-2'>
                  {TRANSITIONS[statusOf(selected)].map((next) => (
                    <Button key={next.key} size='sm' onClick={() => transition(selected, next.key)}>
                      {next.label}
                    </Button>
                  ))}
                  {TRANSITIONS[statusOf(selected)].length === 0 && (
                    <Badge variant='outline' className='text-muted-foreground text-xs'>
                      该 Finding 已闭环
                    </Badge>
                  )}
                </div>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
