import { PageHeader } from '@/components/platform/page-header';
import { NotificationRuleTable } from '@/features/system/components/notification-rule-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Notification'
};

export default function SystemNotificationsPage() {
  const rules = repository.notificationRules();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Notification'
        description='通知规则（PRD 14.5）：平台事件到 Webhook / Email / Slack 的路由配置'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <NotificationRuleTable rules={rules} />
      </div>
    </div>
  );
}
