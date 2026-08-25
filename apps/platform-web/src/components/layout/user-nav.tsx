'use client';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Icons } from '@/components/icons';
import { useRouter } from 'next/navigation';

/**
 * 当前 Operator 展示。
 *
 * 平台当前阶段不引入用户体系，此处显示本地开发身份占位；
 * 接入 OIDC / Operator Identity 后替换为真实会话信息。
 */
export function UserNav() {
  const router = useRouter();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant='ghost' className='h-10 w-full justify-start gap-2 px-2' />}
      >
        <Avatar className='size-8 rounded-lg'>
          <AvatarFallback className='rounded-lg text-xs'>LO</AvatarFallback>
        </Avatar>
        <div className='grid flex-1 text-left leading-tight'>
          <span className='truncate text-sm font-medium'>Local Operator</span>
          <span className='text-muted-foreground truncate text-xs'>
            platform-owner（本地会话）
          </span>
        </div>
        <Icons.chevronsUpDown className='text-muted-foreground size-4' />
      </DropdownMenuTrigger>
      <DropdownMenuContent className='w-56' align='end' sideOffset={8}>
        <DropdownMenuLabel className='font-normal'>
          <div className='flex flex-col space-y-1'>
            <p className='text-sm leading-none font-medium'>Local Operator</p>
            <p className='text-muted-foreground text-xs leading-none'>
              operator@zebra.local
            </p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => router.push('/system/operators')}>
          Operator 与角色
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => router.push('/system/environments')}>
          Environment
        </DropdownMenuItem>
        <DropdownMenuItem disabled>登录（未启用）</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
