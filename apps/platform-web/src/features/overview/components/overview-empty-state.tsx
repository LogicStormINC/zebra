'use client';

import Link from 'next/link';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';

/**
 * 平台总览欢迎空状态（PRD 9.4 四要素：图标 + 标题 + 描述 + 操作）。
 * 尚无 Host 接入时渲染，引导完成首个接入。
 */
export function OverviewEmptyState() {
  return (
    <div className='flex flex-1 items-center justify-center p-8'>
      <div className='flex max-w-md flex-col items-center gap-4 rounded-xl border p-8 text-center'>
        <div className='bg-muted text-muted-foreground flex size-12 items-center justify-center rounded-full'>
          <Icons.platform className='size-6' />
        </div>
        <div className='space-y-1.5'>
          <h2 className='text-lg font-semibold'>欢迎使用 Zebra Agent Platform</h2>
          <p className='text-muted-foreground text-sm'>
            这里是接入与治理中台 Console。接入第一个业务 Host 后，总览将展示接入规模、
            运行质量、安全风险与成本状态。
          </p>
        </div>
        <div className='flex flex-wrap items-center justify-center gap-2'>
          <Button
            render={<Link href='/integrations/onboarding' aria-label='开始第一个 Host 接入' />}
          >
            <Icons.add data-icon='inline-start' />
            开始第一个 Host 接入
          </Button>
          <Button
            variant='outline'
            onClick={() =>
              toast.info('接入文档待接入', {
                description: '文档门户尚未挂载，可先在接入向导内查看各步骤说明'
              })
            }
          >
            <Icons.forms data-icon='inline-start' />
            查看接入文档
          </Button>
          <Button
            variant='outline'
            onClick={() =>
              toast.info('示例配置导入（演示）', {
                description: '将填充一份示例 Host 草稿到接入向导'
              })
            }
          >
            <Icons.sparkles data-icon='inline-start' />
            导入示例配置
          </Button>
        </div>
      </div>
    </div>
  );
}
