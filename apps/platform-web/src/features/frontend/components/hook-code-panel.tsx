'use client';

import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DigestTag } from '@/components/platform/mono-id';
import { Icons } from '@/components/icons';
import type { FrontendProfile } from '@/lib/platform/types';
import {
  HOOK_FILE_NAMES,
  HOOK_FRAMEWORK_LABELS,
  generateHookCode,
  type HookFramework,
  type HookLanguage
} from './hook-code-generator';

/**
 * Hook Contract 面板（PRD 13.7）：
 * 按所选 Frontend Profile 生成三框架 × 双语言示例代码，
 * 只包含 Contract Name / Schema / Provider 配置，不生成业务 Handler 实现。
 */
export function HookCodePanel({ profile }: { profile: FrontendProfile }) {
  const [language, setLanguage] = useState<HookLanguage>('typescript');
  const [framework, setFramework] = useState<HookFramework>('react');
  const [copied, setCopied] = useState(false);

  const frameworks = useMemo<HookFramework[]>(
    () => ['react', 'nextjs', 'copilotkit'],
    []
  );

  const onCopy = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success('代码已复制到剪贴板');
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error('复制失败：剪贴板不可用');
    }
  };

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <p className='text-muted-foreground text-sm'>
          示例代码只包含 Contract Name、Schema 和 Provider
          配置，不生成业务 Handler 实现（PRD 13.7）。
        </p>
        <ButtonGroup>
          <Button
            size='sm'
            className={language === 'typescript' ? 'bg-muted' : ''}
            onClick={() => setLanguage('typescript')}
          >
            TypeScript
          </Button>
          <Button
            size='sm'
            className={language === 'javascript' ? 'bg-muted' : ''}
            onClick={() => setLanguage('javascript')}
          >
            JavaScript
          </Button>
        </ButtonGroup>
      </div>

      <Tabs value={framework} onValueChange={(value) => setFramework(value as HookFramework)}>
        <TabsList className='flex-wrap'>
          {frameworks.map((framework) => (
            <TabsTrigger key={framework} value={framework}>
              {HOOK_FRAMEWORK_LABELS[framework]}
            </TabsTrigger>
          ))}
        </TabsList>
        {frameworks.map((framework) => {
          const code = generateHookCode(profile, framework, language);
          return (
            <TabsContent key={framework} value={framework} className='mt-4'>
              <div className='bg-muted/40 relative overflow-hidden rounded-lg border'>
                <div className='border-b px-3 py-1.5'>
                  <div className='flex items-center justify-between gap-2'>
                    <span className='text-muted-foreground font-mono text-xs'>
                      {HOOK_FILE_NAMES[framework][language]}
                    </span>
                    <Button
                      variant='ghost'
                      size='sm'
                      className='h-6 px-2 text-xs'
                      onClick={() => onCopy(code)}
                    >
                      {copied ? (
                        <Icons.check className='text-emerald-600 size-3' />
                      ) : (
                        <Icons.forms className='size-3' />
                      )}
                      {copied ? '已复制' : '复制'}
                    </Button>
                  </div>
                </div>
                <pre className='overflow-auto p-4 font-mono text-xs leading-relaxed'>
                  {code}
                </pre>
              </div>
            </TabsContent>
          );
        })}
      </Tabs>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>接入信息</CardTitle>
          <CardDescription>
            浏览器端 SDK 只连接同源 BFF，由 BFF 持有签名授权调用平台 API。
          </CardDescription>
        </CardHeader>
        <CardContent className='grid grid-cols-1 gap-4 px-4 py-4 md:grid-cols-2'>
          <div className='space-y-1.5'>
            <p className='text-muted-foreground text-xs'>所需 npm 包</p>
            <div className='flex flex-wrap gap-1.5'>
              <Badge variant='secondary' className='font-mono text-xs'>
                @zebra-agent/react
              </Badge>
              <Badge variant='secondary' className='font-mono text-xs'>
                @zebra-agent/next
              </Badge>
              {framework === 'copilotkit' && (
                <Badge variant='secondary' className='font-mono text-xs'>
                  @copilotkit/react-core
                </Badge>
              )}
            </div>
          </div>
          <div className='space-y-1.5'>
            <p className='text-muted-foreground text-xs'>Frontend Profile Digest</p>
            <DigestTag value={profile.digest} />
          </div>
          <div className='space-y-1.5'>
            <p className='text-muted-foreground text-xs'>当前 Build ID</p>
            <p className='font-mono text-xs font-medium'>{profile.buildId}</p>
          </div>
          <div className='space-y-1.5'>
            <p className='text-muted-foreground text-xs'>BFF 接入说明</p>
            <p className='text-sm'>
              在 Next.js 路由中挂载 <span className='font-mono text-xs'>createZebraBffHandler</span>
              ，平台凭证与 Fence 校验在服务端完成。
            </p>
          </div>
        </CardContent>
      </Card>

      <Alert variant='destructive'>
        <Icons.lock />
        <AlertTitle>禁止 Direct Browser 模式</AlertTitle>
        <AlertDescription>
          浏览器端禁止直接携带平台凭证调用 Agent Runtime API（Direct
          Browser 模式被平台拒绝）：所有请求必须经由同源 BFF 转发。
        </AlertDescription>
      </Alert>
    </div>
  );
}
