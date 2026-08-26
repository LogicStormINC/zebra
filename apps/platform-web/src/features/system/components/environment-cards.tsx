'use client';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { Icons } from '@/components/icons';
import { useEnvironmentStore } from '@/lib/platform/environment-store';
import { formatNumber } from '@/lib/platform/format';
import { cn } from '@/lib/utils';
import type { EnvironmentRecord } from '@/lib/platform/types';
import { toast } from 'sonner';

const STATUS_LABELS: Record<EnvironmentRecord['status'], string> = {
  healthy: '健康',
  degraded: '降级',
  maintenance: '维护中'
};

const STATUS_TONES: Record<EnvironmentRecord['status'], 'success' | 'warning' | 'waiting'> = {
  healthy: 'success',
  degraded: 'warning',
  maintenance: 'waiting'
};

/** Environment 卡片网格（PRD 14.1）：切换全局环境上下文，Production 有额外门禁。 */
export function EnvironmentCards({ environments }: { environments: EnvironmentRecord[] }) {
  const current = useEnvironmentStore((state) => state.environment);
  const setEnvironment = useEnvironmentStore((state) => state.setEnvironment);

  const switchTo = (record: EnvironmentRecord) => {
    setEnvironment(record.id);
    toast.success(`已切换到 ${record.name}`, {
      description: '环境切换影响全局上下文（列表、筛选与后续操作的目标环境）'
    });
  };

  return (
    <div className='flex flex-col gap-4'>
      <Alert>
        <Icons.environment />
        <AlertTitle>环境切换说明</AlertTitle>
        <AlertDescription>
          环境切换影响全局上下文（顶部环境标识、列表数据与操作目标）；Production
          环境有额外门禁，切换需填写审计原因。
        </AlertDescription>
      </Alert>

      <div className='grid grid-cols-1 gap-4 md:grid-cols-3'>
        {environments.map((record) => {
          const isCurrent = current === record.id;
          const isProduction = record.id === 'production';
          return (
            <Card
              key={record.id}
              className={cn(
                'gap-3 py-0 transition-shadow hover:shadow-md',
                isCurrent && 'ring-primary ring-2'
              )}
            >
              <CardHeader className='flex flex-row items-center justify-between space-y-0 border-b px-4 py-3'>
                <CardTitle className='flex items-center gap-2 text-sm'>
                  <Icons.environment className='size-4' />
                  {record.name}
                  {isCurrent && (
                    <Badge className='px-1.5 text-[10px]' variant='default'>
                      当前
                    </Badge>
                  )}
                </CardTitle>
                <StatusBadge tone={STATUS_TONES[record.status]}>{STATUS_LABELS[record.status]}</StatusBadge>
              </CardHeader>
              <CardContent className='flex flex-col gap-3 px-4 py-3'>
                <div className='space-y-1.5 text-sm'>
                  <p className='flex items-center justify-between gap-2'>
                    <span className='text-muted-foreground text-xs'>API Endpoint</span>
                    <code className='bg-muted rounded px-1.5 py-0.5 font-mono text-xs break-all'>
                      {record.apiEndpoint}
                    </code>
                  </p>
                  <p className='flex items-center justify-between gap-2'>
                    <span className='text-muted-foreground text-xs'>Region</span>
                    <span className='text-xs'>{record.region}</span>
                  </p>
                  <p className='flex items-center justify-between gap-2'>
                    <span className='text-muted-foreground text-xs'>Hosts</span>
                    <span className='font-mono text-xs tabular-nums'>{record.hosts}</span>
                  </p>
                  <p className='flex items-center justify-between gap-2'>
                    <span className='text-muted-foreground text-xs'>24h Tasks</span>
                    <span className='font-mono text-xs tabular-nums'>{formatNumber(record.tasks24h)}</span>
                  </p>
                </div>
                <div className='flex justify-end'>
                  {isCurrent ? (
                    <Badge variant='outline' className='text-muted-foreground text-xs'>
                      当前全局上下文
                    </Badge>
                  ) : isProduction ? (
                    <RiskConfirmDialog
                      trigger={<Button size='sm' variant='outline'>设为当前环境</Button>}
                      title='切换到 Production'
                      impact='全局上下文切换到 Production：后续列表与操作均指向生产环境数据'
                      irreversibility='切换本身可逆，但生产环境内的操作影响真实业务 Host'
                      actionLabel='确认切换'
                      onConfirm={() => switchTo(record)}
                    />
                  ) : (
                    <Button size='sm' variant='outline' onClick={() => switchTo(record)}>
                      设为当前环境
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
