'use client';
import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
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
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId } from '@/components/platform/mono-id';
import { RiskBadge } from '@/components/platform/risk-badge';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDuration, formatNumber, formatUsd } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import type { Attempt, ModelCall, ToolCall } from '@/lib/platform/types';

const OUTCOME_META: Record<Attempt['outcome'], { label: string; tone: 'success' | 'failure' | 'running' }> = {
  succeeded: { label: '成功', tone: 'success' },
  failed: { label: '失败', tone: 'failure' },
  retried: { label: '已重试', tone: 'running' }
};

const LOCATION_LABELS: Record<ToolCall['executionLocation'], string> = {
  zebra: 'Zebra',
  host: 'Host',
  sandbox: 'Sandbox',
  client: 'Client'
};

const LOCATION_TONES: Record<ToolCall['executionLocation'], 'draft' | 'running' | 'waiting' | 'uncertain'> = {
  zebra: 'draft',
  host: 'running',
  sandbox: 'waiting',
  client: 'uncertain'
};

/** Attempts Tab（PRD 18.8）：Attempt Number / Lease Fence / 模型消耗 / 结果。 */
export function TaskAttemptsTab({ attempts }: { attempts: Attempt[] }) {
  if (attempts.length === 0) {
    return (
      <EmptyState
        icon='task'
        title='暂无 Attempt 记录'
        description='Task 被 Worker 认领后会生成带 Lease Fence 的 Attempt；失败重试会追加新行'
      />
    );
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Attempt</TableHead>
            <TableHead>Lease Fence</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>Tokens（入 / 出 / 推理）</TableHead>
            <TableHead>Tool Calls</TableHead>
            <TableHead>Duration</TableHead>
            <TableHead>Outcome</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {attempts.map((attempt) => (
            <TableRow key={attempt.attemptNumber}>
              <TableCell className='font-medium tabular-nums'>#{attempt.attemptNumber}</TableCell>
              <TableCell>
                <MonoId value={attempt.leaseFence} />
              </TableCell>
              <TableCell className='font-mono text-xs'>{attempt.model}</TableCell>
              <TableCell className='tabular-nums text-sm'>
                {formatNumber(attempt.inputTokens)} / {formatNumber(attempt.outputTokens)} /{' '}
                {formatNumber(attempt.reasoningTokens)}
              </TableCell>
              <TableCell className='tabular-nums'>{attempt.toolCalls}</TableCell>
              <TableCell className='tabular-nums'>{formatDuration(attempt.durationSeconds * 1000)}</TableCell>
              <TableCell>
                <StatusBadge tone={OUTCOME_META[attempt.outcome].tone}>
                  {OUTCOME_META[attempt.outcome].label}
                </StatusBadge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

const THINKING_LABELS: Record<ModelCall['thinkingMode'], string> = {
  disabled: '关闭',
  medium: '中',
  max: '最大'
};

/** Model Calls Tab（PRD 18.8）：请求/解析模型、thinking、延迟与成本；Prompt 受权限控制。 */
export function TaskModelCallsTab({ modelCalls }: { modelCalls: ModelCall[] }) {
  if (modelCalls.length === 0) {
    return (
      <EmptyState
        icon='usage'
        title='暂无模型调用'
        description='Executor / Planner 等角色的模型调用会按 role 记录在此'
      />
    );
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Role</TableHead>
            <TableHead>Provider</TableHead>
            <TableHead>Requested / Resolved</TableHead>
            <TableHead>Thinking</TableHead>
            <TableHead>Latency</TableHead>
            <TableHead>Retry</TableHead>
            <TableHead>Finish Reason</TableHead>
            <TableHead>Usage Tokens</TableHead>
            <TableHead>Cost</TableHead>
            <TableHead className='text-right'>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {modelCalls.map((call) => (
            <TableRow key={call.id}>
              <TableCell>
                <Badge variant='outline'>{call.role}</Badge>
              </TableCell>
              <TableCell className='text-sm'>{call.provider}</TableCell>
              <TableCell className='font-mono text-xs'>
                {call.requestedModel}
                <Icons.arrowRight className='text-muted-foreground mx-1 inline size-3' />
                {call.resolvedModel}
              </TableCell>
              <TableCell className='text-sm'>{THINKING_LABELS[call.thinkingMode]}</TableCell>
              <TableCell className='tabular-nums'>{formatDuration(call.latencyMs)}</TableCell>
              <TableCell className='tabular-nums'>{call.retryCount}</TableCell>
              <TableCell className='font-mono text-xs'>{call.finishReason}</TableCell>
              <TableCell className='tabular-nums text-xs'>
                入 {formatNumber(call.inputTokens)} / 出 {formatNumber(call.outputTokens)} / 推理{' '}
                {formatNumber(call.reasoningTokens)}
              </TableCell>
              <TableCell className='tabular-nums'>{formatUsd(call.costUsd)}</TableCell>
              <TableCell className='text-right'>
                <ModelCallPromptDialog call={call} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ModelCallPromptDialog({ call }: { call: ModelCall }) {
  return (
    <Dialog>
      <DialogTrigger render={<Button variant='outline' size='sm' />}>Prompt</DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>
            {call.role} · {call.id}
          </DialogTitle>
          <DialogDescription>Prompt 内容受权限控制</DialogDescription>
        </DialogHeader>
        <div className='text-muted-foreground space-y-2 text-sm'>
          <p className='flex items-start gap-2'>
            <Icons.lock className='mt-0.5 size-4 shrink-0' />
            本次调用的完整 Prompt 与 Response 仅对具备 <span className='font-mono'>prompt:read</span>{' '}
            权限的操作员可见；中台默认仅展示元数据与 Usage 统计。
          </p>
          <p>
            元数据：provider {call.provider}，resolved {call.resolvedModel}，thinking{' '}
            {THINKING_LABELS[call.thinkingMode]}，finish {call.finishReason}。
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const TOOL_STATUS_LABELS: Record<ToolCall['status'], string> = {
  succeeded: '成功',
  failed: '失败',
  running: '运行中',
  awaiting_approval: '待审批'
};

const RISK_LABELS: Record<ToolCall['risk'], string> = {
  read: 'Read',
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  presentation: '展示',
  navigation: '导航',
  local_state: '本地状态',
  user_interaction: '用户交互'
};

const FILTER_ALL = 'all';

/** Tools Tab（PRD 18.9）：执行位置 / 风险筛选 + Scope / Arguments Digest / Receipt。 */
export function TaskToolsTab({ toolCalls }: { toolCalls: ToolCall[] }) {
  const [locationFilter, setLocationFilter] = useState<string>(FILTER_ALL);
  const [riskFilter, setRiskFilter] = useState<string>(FILTER_ALL);

  if (toolCalls.length === 0) {
    return (
      <EmptyState
        icon='hook'
        title='暂无工具调用'
        description='Agent 的每一次工具调用（zebra / host / sandbox / client）都会记录 digest 与 Receipt'
      />
    );
  }

  const locationItems: Record<string, string> = {
    [FILTER_ALL]: '全部位置',
    ...LOCATION_LABELS
  };
  const riskItems: Record<string, string> = { [FILTER_ALL]: '全部风险', ...RISK_LABELS };

  const filtered = toolCalls.filter(
    (call) =>
      (locationFilter === FILTER_ALL || call.executionLocation === locationFilter) &&
      (riskFilter === FILTER_ALL || call.risk === riskFilter)
  );

  return (
    <div className='flex flex-col gap-3'>
      <div className='flex items-center gap-2'>
        <Select
          items={locationItems}
          value={locationFilter}
          onValueChange={(value) => setLocationFilter(String(value ?? FILTER_ALL))}
        >
          <SelectTrigger className='w-44' aria-label='按执行位置筛选'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value={FILTER_ALL}>全部位置</SelectItem>
              {(Object.keys(LOCATION_LABELS) as ToolCall['executionLocation'][]).map((location) => (
                <SelectItem key={location} value={location}>
                  {LOCATION_LABELS[location]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          items={riskItems}
          value={riskFilter}
          onValueChange={(value) => setRiskFilter(String(value ?? FILTER_ALL))}
        >
          <SelectTrigger className='w-44' aria-label='按风险等级筛选'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value={FILTER_ALL}>全部风险</SelectItem>
              {(Object.keys(RISK_LABELS) as ToolCall['risk'][]).map((risk) => (
                <SelectItem key={risk} value={risk}>
                  {RISK_LABELS[risk]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <span className='text-muted-foreground text-xs'>
          {filtered.length} / {toolCalls.length} 条工具调用
        </span>
      </div>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Tool Call ID</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Execution Location</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Scope</TableHead>
              <TableHead>Arguments Digest</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Receipt</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className='text-muted-foreground h-24 text-center text-sm'>
                  无符合条件的工具调用
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((call) => (
                <TableRow key={call.id}>
                  <TableCell>
                    <MonoId value={call.id} copyable={false} />
                  </TableCell>
                  <TableCell className='font-mono text-xs font-medium'>{call.toolName}</TableCell>
                  <TableCell>
                    <StatusBadge tone={LOCATION_TONES[call.executionLocation]} withDot={false}>
                      {LOCATION_LABELS[call.executionLocation]}
                    </StatusBadge>
                  </TableCell>
                  <TableCell>
                    <RiskBadge risk={call.risk} />
                  </TableCell>
                  <TableCell className='font-mono text-xs'>{call.scope}</TableCell>
                  <TableCell>
                    <MonoId value={call.argumentsDigest} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge
                      tone={
                        call.status === 'succeeded'
                          ? 'success'
                          : call.status === 'failed'
                            ? 'failure'
                            : call.status === 'running'
                              ? 'running'
                              : 'waiting'
                      }
                    >
                      {TOOL_STATUS_LABELS[call.status]}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className='tabular-nums'>
                    {call.status === 'awaiting_approval' ? '—' : formatDuration(call.durationMs)}
                  </TableCell>
                  <TableCell>
                    {call.receiptDigest ? (
                      <MonoId value={call.receiptDigest} />
                    ) : (
                      <span className='text-muted-foreground text-xs'>
                        <StatusBadge tone={lifecycleTone('missing_receipt')}>无 Receipt</StatusBadge>
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
