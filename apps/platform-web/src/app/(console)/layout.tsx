import KBar from '@/components/kbar';
import AppSidebar from '@/components/layout/app-sidebar';
import Header from '@/components/layout/header';
import { EnvironmentBanner } from '@/components/layout/environment-banner';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import type { Metadata } from 'next';
import { cookies } from 'next/headers';

export const metadata: Metadata = {
  title: 'Zebra Agent Platform Console',
  description: 'Zebra 智能体接入与治理中台',
  robots: {
    index: false,
    follow: false
  }
};

/**
 * 控制台 Shell（PRD 第 8 章）。
 *
 * 当前阶段不启用登录门禁；接入 Operator Identity 后，
 * 在此布局中恢复认证重定向与初始权限装载。
 */
export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const defaultOpen = cookieStore.get('sidebar_state')?.value === 'true';

  return (
    <KBar>
      <SidebarProvider defaultOpen={defaultOpen}>
        <a
          href='#main-content'
          className='bg-background ring-ring sr-only rounded-md px-3 py-2 text-sm font-medium shadow focus:not-sr-only focus:absolute focus:top-2 focus:start-2 focus:z-50 focus:ring-2'
        >
          Skip to content
        </a>
        <AppSidebar />
        <SidebarInset id='main-content' tabIndex={-1} className='scroll-mt-16'>
          <Header />
          <EnvironmentBanner />
          <div className='flex flex-1 flex-col'>{children}</div>
        </SidebarInset>
      </SidebarProvider>
    </KBar>
  );
}
