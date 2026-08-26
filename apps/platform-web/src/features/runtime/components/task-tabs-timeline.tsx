'use client';
import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
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
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/platform/empty-state';
import { JsonBlock } from '@/components/platform/json-block';
import { MonoId } from '@/components/platform/mono-id';
import { formatDateTime } from '@/lib/platform/format';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import type { TaskEvent, TaskEventType } from '@/lib/platform/types';

/** tool_call / host_effect_dispatched / client_effect_dispatched 的行内跳转目标。 */
const JUMP_TARGETS: Partial<Record<TaskEventType, { tab: string; label: string }>> = {
  tool_call: { tab: 'tools', label: 'Tools' },
  host_effect_dispatched: { tab: 'host-effects', label: 'Host Effects' },
  client_effect_dispatched: { tab: 'client', label: 'Client' }
};

async function copyEventId(eventId: string) {
  try {
    await navigator.clipboard.writeText(eventId);
    toast.success('Event ID 已复制', { description: eventId });
  } catch {
    toast.error('复制失败', { description: '剪贴板不可用' });
  }
}

/** Timeline Tab（PRD 18.6）：事件流表 + type 筛选 + JSON 查看 + 关联 Tab 跳转。 */
export function TaskTimelineTab({
  events,
  onNavigateTab
}: {
  events: TaskEvent[];
  onNavigateTab?: (tab: string) => void;
}) {
  const [typeFilter, setTypeFilter] = useState<string>('all');

  const sorted = useMemo(() => events.toSorted((a, b) => a.sequence - b.sequence), [events]);
  const availableTypes = useMemo(() => [...new Set(sorted.map((event) => event.type))], [sorted]);
  const filtered = useMemo(
    () => (typeFilter === 'all' ? sorted : sorted.filter((event) => event.type === typeFilter)),
    [sorted, typeFilter]
  );

  if (events.length === 0) {
    return (
      <EmptyState
        icon='audit'
        title='该 Task 暂无事件'
        description='事件按 sequence 追加写入 Durable Event Store，是 Task 的唯一事实来源'
      />
    );
  }

  const selectItems: Record<string, string> = { all: '全部类型', ...Object.fromEntries(availableTypes.map((type) => [type, type])) };

  return (
    <div className='flex flex-col gap-3'>
      <div className='flex items-center gap-2'>
        <Select
          items={selectItems}
          value={typeFilter}
          onValueChange={(value) => setTypeFilter(String(value ?? 'all'))}
        >
          <SelectTrigger className='w-56'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部类型</SelectItem>
              {availableTypes.map((type: TaskEventType) => (
                <SelectItem key={type} value={type}>
                  {type}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <span className='text-muted-foreground text-xs'>
          {filtered.length} / {sorted.length} 条事件（按 sequence 升序）
        </span>
      </div>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Seq</TableHead>
              <TableHead>Event ID</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Timestamp</TableHead>
              <TableHead>Summary</TableHead>
              <TableHead>Policy Version</TableHead>
              <TableHead>Model Profile</TableHead>
              <TableHead>Causation</TableHead>
              <TableHead>Correlation</TableHead>
              <TableHead className='text-right'>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((event) => (
              <TableRow key={event.eventId}>
                <TableCell className='tabular-nums'>{event.sequence}</TableCell>
                <TableCell>
                  <MonoId value={event.eventId} copyable={false} />
                </TableCell>
                <TableCell>
                  <Badge variant='outline' className='font-mono text-xs'>
                    {event.type}
                  </Badge>
                </TableCell>
                <TableCell className='font-mono text-xs'>{event.actor}</TableCell>
                <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(event.timestamp)}</TableCell>
                <TableCell className='max-w-[280px] text-sm'>{event.summary}</TableCell>
                <TableCell>
                  {event.policyVersion ? (
                    <span className='font-mono text-xs'>{event.policyVersion}</span>
                  ) : (
                    <span className='text-muted-foreground text-xs'>—</span>
                  )}
                </TableCell>
                <TableCell>
                  {event.modelProfile ? (
                    <span className='font-mono text-xs'>{event.modelProfile}</span>
                  ) : (
                    <span className='text-muted-foreground text-xs'>—</span>
                  )}
                </TableCell>
                <TableCell>
                  {event.causationId ? <MonoId value={event.causationId} copyable={false} /> : '—'}
                </TableCell>
                <TableCell>
                  {event.correlationId ? <MonoId value={event.correlationId} copyable={false} /> : '—'}
                </TableCell>
                <TableCell className='text-right'>
                  <span className='inline-flex items-center gap-1'>
                    {onNavigateTab && JUMP_TARGETS[event.type] && (
                      <Button
                        variant='ghost'
                        size='sm'
                        className='text-primary'
                        onClick={() => onNavigateTab(JUMP_TARGETS[event.type]!.tab)}
                      >
                        跳转 {JUMP_TARGETS[event.type]!.label}
                        <Icons.arrowRight className='size-3.5' />
                      </Button>
                    )}
                    <EventJsonDialog event={event} />
                    <Button
                      variant='ghost'
                      size='icon-sm'
                      aria-label='复制 Event ID'
                      onClick={() => void copyEventId(event.eventId)}
                    >
                      <Icons.forms className='size-3.5' />
                    </Button>
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function EventJsonDialog({ event }: { event: TaskEvent }) {
  return (
    <Dialog>
      <DialogTrigger render={<Button variant='outline' size='sm' />}>查看 JSON</DialogTrigger>
      <DialogContent className='sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle className='font-mono text-sm'>{event.eventId}</DialogTitle>
          <DialogDescription>
            seq {event.sequence} · {event.type} · {event.actor}
          </DialogDescription>
        </DialogHeader>
        <JsonBlock title={`${event.eventId}.json`} value={event} maxHeight={360} />
      </DialogContent>
    </Dialog>
  );
}
