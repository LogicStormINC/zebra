'use client';

import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { RiskBadge } from '@/components/platform/risk-badge';
import { StatusBadge } from '@/components/platform/status-badge';
import { Icons } from '@/components/icons';
import { formatBytes, formatDuration } from '@/lib/platform/format';
import type { FrontendProfile } from '@/lib/platform/types';
import { SensitivityBadge } from './sensitivity-badge';
import {
  EXECUTION_MODE_LABELS,
  EXECUTION_MODE_TONES,
  FORBIDDEN_READABLE_ITEMS,
  UPDATE_STRATEGY_LABELS
} from './labels';

/** Readables Tab（PRD 13.4）：契约表 + 禁止接入项说明。 */
export function ProfileReadablesTab({ profile }: { profile: FrontendProfile }) {
  return (
    <div className='flex flex-col gap-4'>
      <div className='overflow-x-auto rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Sensitivity</TableHead>
              <TableHead>Max Bytes</TableHead>
              <TableHead>Update Strategy</TableHead>
              <TableHead className='text-center'>Context Priority</TableHead>
              <TableHead className='text-right'>校验</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {profile.readables.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className='text-muted-foreground h-20 text-center'>
                  该 Profile 未声明 Readables
                </TableCell>
              </TableRow>
            ) : (
              profile.readables.map((readable) => (
                <TableRow key={readable.name}>
                  <TableCell className='font-mono text-xs'>{readable.name}</TableCell>
                  <TableCell className='max-w-64 truncate text-sm'>
                    {readable.description}
                  </TableCell>
                  <TableCell>
                    <SensitivityBadge sensitivity={readable.sensitivity} />
                  </TableCell>
                  <TableCell className='tabular-nums'>{formatBytes(readable.maxBytes)}</TableCell>
                  <TableCell className='text-sm'>
                    {UPDATE_STRATEGY_LABELS[readable.updateStrategy]}（{readable.updateStrategy}）
                  </TableCell>
                  <TableCell className='text-center tabular-nums'>
                    {readable.contextPriority}
                  </TableCell>
                  <TableCell className='text-right'>
                    <Button
                      size='xs'
                      variant='outline'
                      className='mr-1.5'
                      onClick={() =>
                        toast.info(`脱敏预览：${readable.name}`, {
                          description:
                            readable.sensitivity === 'public'
                              ? '公开数据：按原文注入上下文'
                              : '按敏感度执行脱敏后注入上下文，平台仅保留脱敏摘要'
                        })
                      }
                    >
                      脱敏预览
                    </Button>
                    <Button
                      size='xs'
                      variant='outline'
                      onClick={() =>
                        toast.success(`示例值校验通过：${readable.name}`, {
                          description: `示例值大小与 Schema 校验未超过 ${formatBytes(readable.maxBytes)} 上限`
                        })
                      }
                    >
                      示例值校验
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Alert>
        <Icons.lock />
        <AlertTitle>禁止接入的 Readable 项（PRD 13.4）</AlertTitle>
        <AlertDescription>
          以下内容不允许声明为 Readable，接入校验会直接拒绝：
          <span className='mt-1.5 flex flex-wrap gap-1.5'>
            {FORBIDDEN_READABLE_ITEMS.map((item) => (
              <Badge key={item} variant='destructive'>
                {item}
              </Badge>
            ))}
          </span>
        </AlertDescription>
      </Alert>
    </div>
  );
}

/** Actions Tab（PRD 13.5）：契约表 + 校验规则说明。 */
export function ProfileActionsTab({ profile }: { profile: FrontendProfile }) {
  return (
    <div className='flex flex-col gap-4'>
      <div className='overflow-x-auto rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Capability</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Execution Mode</TableHead>
              <TableHead>Timeout</TableHead>
              <TableHead className='text-center'>Requires Controller</TableHead>
              <TableHead className='text-center'>Requires User Confirmation</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {profile.actions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className='text-muted-foreground h-20 text-center'>
                  该 Profile 未声明 Actions
                </TableCell>
              </TableRow>
            ) : (
              profile.actions.map((action) => (
                <TableRow key={action.name}>
                  <TableCell>
                    <p className='font-mono text-xs'>{action.name}</p>
                    <p className='text-muted-foreground max-w-56 truncate text-xs'>
                      {action.description}
                    </p>
                  </TableCell>
                  <TableCell className='font-mono text-xs'>{action.capability}</TableCell>
                  <TableCell>
                    <RiskBadge risk={action.risk} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={EXECUTION_MODE_TONES[action.executionMode]} withDot={false}>
                      {EXECUTION_MODE_LABELS[action.executionMode]}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className='tabular-nums'>{formatDuration(action.timeoutMs)}</TableCell>
                  <TableCell className='text-center'>
                    {action.requiresController ? (
                      <Icons.check className='text-emerald-600 mx-auto size-4' />
                    ) : (
                      <span className='text-muted-foreground'>—</span>
                    )}
                  </TableCell>
                  <TableCell className='text-center'>
                    {action.requiresUserConfirmation ? (
                      <Icons.check className='text-emerald-600 mx-auto size-4' />
                    ) : (
                      <span className='text-muted-foreground'>—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Alert>
        <Icons.security />
        <AlertTitle>Action 校验规则（PRD 13.5）</AlertTitle>
        <AlertDescription className='space-y-1'>
          <p>1. Client Action 不允许声明正式业务写入：业务数据变更必须走 Backend Manifest 的写工具与 HostGrant 审批链路。</p>
          <p>
            2. <span className='font-mono text-xs'>human_confirmed</span>{' '}
            执行模式必须配置确认 UI：缺少确认 UI 的 Action 无法通过 Frontend Conformance。
          </p>
        </AlertDescription>
      </Alert>
    </div>
  );
}

/** Components Tab（PRD 13.6）：注册式组件清单 + V1 限制说明。 */
export function ProfileComponentsTab({ profile }: { profile: FrontendProfile }) {
  return (
    <div className='flex flex-col gap-4'>
      <div className='overflow-x-auto rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Component ID</TableHead>
              <TableHead>说明</TableHead>
              <TableHead>Props Schema</TableHead>
              <TableHead>Allowed Slots</TableHead>
              <TableHead>Max Instances</TableHead>
              <TableHead>Requires Resource Binding</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {profile.components.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className='text-muted-foreground h-20 text-center'>
                  该 Profile 未注册组件
                </TableCell>
              </TableRow>
            ) : (
              profile.components.map((component) => (
                <TableRow key={component}>
                  <TableCell className='font-mono text-xs'>{component}</TableCell>
                  <TableCell className='text-sm'>注册式组件（元数据随 Build 产物提交）</TableCell>
                  <TableCell className='text-muted-foreground font-mono text-xs'>
                    build://{profile.buildId}/{component}.schema.json
                  </TableCell>
                  <TableCell className='text-muted-foreground text-sm'>host 声明的 slot</TableCell>
                  <TableCell className='text-muted-foreground text-sm'>—</TableCell>
                  <TableCell className='text-muted-foreground text-sm'>—</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Alert variant='destructive'>
        <Icons.warning />
        <AlertTitle>V1 组件限制（PRD 13.6）</AlertTitle>
        <AlertDescription>
          V1 仅支持注册式组件：Agent 只能引用 Profile 中声明的 Component
          ID。禁止任意 JSX / HTML / Script / CSS 注入，禁止远程加载组件代码。
        </AlertDescription>
      </Alert>
    </div>
  );
}
