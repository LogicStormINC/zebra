'use client';
import React from 'react';
import { SidebarTrigger } from '../ui/sidebar';
import { Separator } from '../ui/separator';
import { Breadcrumbs } from '../breadcrumbs';
import SearchInput from '../search-input';
import { ThemeModeToggle } from '../themes/theme-mode-toggle';
import { Icons } from '@/components/icons';
import { Badge } from '../ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';
import {
  ENVIRONMENTS,
  environmentNamespace,
  useEnvironmentStore
} from '@/lib/platform/environment-store';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '../ui/select';

/**
 * 顶部栏（PRD 8.2）：
 * 环境选择、Namespace、全局搜索、待处理 Approval、
 * Uncertain Effect、平台健康状态与 Operator 菜单（侧栏底部）。
 */
export default function Header() {
  const environment = useEnvironmentStore((state) => state.environment);
  const setEnvironment = useEnvironmentStore((state) => state.setEnvironment);

  return (
    <header className='bg-background/60 sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between gap-2 px-4 backdrop-blur-md md:h-14'>
      <div className='flex items-center gap-2'>
        <SidebarTrigger className='-ml-1' />
        <Separator orientation='vertical' className='mr-2 h-4 data-vertical:self-center' />
        <Breadcrumbs />
      </div>

      <div className='flex items-center gap-2'>
        <Select
          value={environment}
          onValueChange={(value) => setEnvironment(value as typeof environment)}
        >
          <SelectTrigger
            size='sm'
            className='bg-background hidden h-8 w-[150px] gap-1 sm:flex'
            aria-label='Environment'
          >
            <SelectValue placeholder='Environment' />
          </SelectTrigger>
          <SelectContent>
            {ENVIRONMENTS.map((env) => (
              <SelectItem key={env.id} value={env.id}>
                <span className='flex items-center gap-2'>
                  {env.label}
                  {env.id === 'production' && (
                    <span className='bg-destructive/15 text-destructive rounded px-1 text-[10px] font-medium'>
                      PROD
                    </span>
                  )}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Badge variant='outline' className='text-muted-foreground hidden font-mono text-xs lg:flex'>
          ns/{environmentNamespace(environment)}
        </Badge>

        <Tooltip>
          <TooltipTrigger
            render={
              <Badge
                variant='outline'
                className='cursor-default gap-1 text-amber-600 dark:text-amber-400'
              >
                <Icons.approval className='size-3.5' />
                Approval 2
              </Badge>
            }
          />
          <TooltipContent>待处理 Approval：2</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger
            render={
              <Badge variant='outline' className='cursor-default gap-1 text-orange-600 dark:text-orange-400'>
                <Icons.effect className='size-3.5' />
                Uncertain 1
              </Badge>
            }
          />
          <TooltipContent>Uncertain Effect：1</TooltipContent>
        </Tooltip>

        <div className='hidden md:flex'>
          <SearchInput />
        </div>
        <ThemeModeToggle />
        <Tooltip>
          <TooltipTrigger
            render={
              <span className='border-input bg-background text-emerald-600 dark:text-emerald-400 flex size-8 items-center justify-center rounded-md border'>
                <Icons.heartbeat className='size-4' />
              </span>
            }
          />
          <TooltipContent>Platform Health：正常</TooltipContent>
        </Tooltip>
      </div>
    </header>
  );
}
