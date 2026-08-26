'use client';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail
} from '@/components/ui/sidebar';
import { navGroups } from '@/config/nav-config';
import { useFilteredNavGroups } from '@/hooks/use-nav';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import * as React from 'react';
import { cn } from '@/lib/utils';
import { Icons } from '../icons';
import { ZebraLogo } from '@/components/zebra-logo';
import { UserNav } from './user-nav';

function isSegmentActive(pathname: string, url: string) {
  if (pathname === url) return true;
  // 命名冲突的二级路由（例如 /agents/policies/models）必须整段匹配
  return pathname.startsWith(`${url}/`);
}

export default function AppSidebar() {
  const pathname = usePathname();
  const filteredGroups = useFilteredNavGroups(navGroups);

  return (
    <Sidebar collapsible='icon'>
      <SidebarHeader className='group-data-[collapsible=icon]:pt-4'>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size='lg'
              render={<Link href='/overview' aria-label='Zebra Agent Platform' />}
              className='gap-3'
            >
              <ZebraLogo className='size-8 shrink-0' />
              <div className='grid flex-1 text-left leading-tight'>
                <span className='truncate font-semibold'>Zebra Agent Platform</span>
                <span className='text-muted-foreground truncate text-xs'>
                  接入与治理中台 Console
                </span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent className='overflow-x-hidden'>
        {filteredGroups.map((group) => (
          <SidebarGroup key={group.label || 'ungrouped'} className='py-0'>
            {group.label && <SidebarGroupLabel>{group.label}</SidebarGroupLabel>}
            <SidebarMenu>
              {group.items.map((item) => {
                const Icon = item.icon ? Icons[item.icon] : Icons.logo;
                return item?.items && item?.items?.length > 0 ? (
                  <Collapsible
                    key={item.title}
                    defaultOpen={item.isActive}
                    render={<SidebarMenuItem />}
                  >
                    <CollapsibleTrigger
                      render={
                        <SidebarMenuButton
                          tooltip={item.title}
                          isActive={isSegmentActive(pathname, item.url)}
                          className='group/collapsible'
                        />
                      }
                    >
                      {item.icon && <Icon />}
                      <span>{item.title}</span>
                      {item.badge && (
                        <span className='bg-destructive text-destructive-foreground ml-auto min-w-4 rounded-full px-1 text-center text-[10px] leading-4 font-semibold tabular-nums group-data-[collapsible=icon]:hidden'>
                          {item.badge}
                        </span>
                      )}
                      <Icons.chevronRight
                        className={cn(
                          'transition-transform duration-200 group-data-panel-open/collapsible:rotate-90',
                          item.badge ? '' : 'ml-auto'
                        )}
                      />
                    </CollapsibleTrigger>
                    <CollapsibleContent className='CollapsibleContent'>
                      <SidebarMenuSub>
                        {item.items.map((subItem) => (
                          <SidebarMenuSubItem key={subItem.title}>
                            <SidebarMenuSubButton
                              render={<Link href={subItem.url} aria-label={subItem.title} />}
                              isActive={pathname === subItem.url}
                            >
                              <span>{subItem.title}</span>
                            </SidebarMenuSubButton>
                          </SidebarMenuSubItem>
                        ))}
                      </SidebarMenuSub>
                    </CollapsibleContent>
                  </Collapsible>
                ) : (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      render={<Link href={item.url} aria-label={item.title} />}
                      tooltip={item.title}
                      isActive={isSegmentActive(pathname, item.url)}
                    >
                      {item.icon && <Icon />}
                      <span>{item.title}</span>
                      {item.badge && (
                        <span className='bg-destructive text-destructive-foreground ml-auto min-w-4 rounded-full px-1 text-center text-[10px] leading-4 font-semibold tabular-nums group-data-[collapsible=icon]:hidden'>
                          {item.badge}
                        </span>
                      )}
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <div className='px-2 py-1'>
          <UserNav />
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
