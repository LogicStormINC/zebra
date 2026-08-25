'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import {
  EMPTY_DRAFT,
  ONBOARDING_STEPS,
  type OnboardingDraft,
  clearDraft,
  completedSteps,
  isStepComplete,
  loadDraft,
  saveDraft
} from '../lib/onboarding-state';
import type { AgentOption } from './onboarding-step-agents';
import { OnboardingStepAgents } from './onboarding-step-agents';
import { OnboardingStepBasic } from './onboarding-step-basic';
import { OnboardingStepConnector } from './onboarding-step-connector';
import { OnboardingStepFrontend } from './onboarding-step-frontend';
import { OnboardingStepManifest } from './onboarding-step-manifest';
import { OnboardingStepPublish } from './onboarding-step-publish';
import { OnboardingStepTrust } from './onboarding-step-trust';

/** 7 步接入向导（PRD 10.3）：Stepper + 步骤表单 + 检查清单 + localStorage 草稿。 */
export function OnboardingWizard({
  agentReleases,
  capabilityProfiles,
  policies,
  quotas,
  capabilityCeilings
}: {
  agentReleases: AgentOption[];
  capabilityProfiles: AgentOption[];
  policies: AgentOption[];
  quotas: AgentOption[];
  capabilityCeilings: Record<string, string[]>;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<OnboardingDraft>(EMPTY_DRAFT);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    // 挂载时从 localStorage 同步一次草稿；SSR/首帧保持 EMPTY_DRAFT 以避免 hydration 不一致
    const restoreDraft = () => {
      const restored = loadDraft();
      if (restored) {
        setDraft(restored);
        toast.info('已恢复未完成的接入草稿', { description: '草稿保存在本地浏览器（zebra-onboarding-draft）' });
      }
      setHydrated(true);
    };
    restoreDraft();
  }, []);

  useEffect(() => {
    if (hydrated) saveDraft(draft);
  }, [draft, hydrated]);

  const step = draft.step;
  const done = completedSteps(draft);
  const currentComplete = isStepComplete(draft, step);
  const canGoNext = step < 7 && currentComplete;

  const goToStep = (next: number) => setDraft((prev) => ({ ...prev, step: next }));

  const next = () => {
    if (!currentComplete) {
      toast.error('请先完成当前步骤的必填项');
      return;
    }
    goToStep(Math.min(7, step + 1));
  };

  const saveAndExit = () => {
    saveDraft(draft);
    toast.success('草稿已保存到本地', { description: '可随时从「接入向导」继续' });
    router.push('/integrations/hosts');
  };

  const onPublished = () => {
    clearDraft();
    setDraft(EMPTY_DRAFT);
    router.push('/integrations/hosts');
  };

  return (
    <div className='grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_300px]'>
      <div className='flex min-w-0 flex-col gap-6'>
        {/* Stepper */}
        <ol className='flex flex-wrap items-center gap-2'>
          {ONBOARDING_STEPS.map((title, index) => {
            const stepIndex = index + 1;
            const isCurrent = stepIndex === step;
            const isDone = done[index] && stepIndex <= step;
            const reachable = stepIndex <= step;
            return (
              <li key={title} className='flex items-center gap-2'>
                <button
                  type='button'
                  disabled={!reachable}
                  onClick={() => reachable && goToStep(stepIndex)}
                  className={cn(
                    'flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                    isCurrent
                      ? 'border-primary bg-primary text-primary-foreground'
                      : isDone
                        ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                        : 'text-muted-foreground',
                    reachable && !isCurrent && 'hover:bg-muted'
                  )}
                >
                  <span
                    className={cn(
                      'flex size-5 items-center justify-center rounded-full border text-[10px] tabular-nums',
                      isCurrent
                        ? 'border-primary-foreground/40'
                        : isDone
                          ? 'border-emerald-500/40'
                          : 'border-muted-foreground/40'
                    )}
                  >
                    {isDone && !isCurrent ? <Icons.check className='size-3' /> : stepIndex}
                  </span>
                  {title}
                </button>
                {stepIndex < 7 && <Icons.chevronRight className='text-muted-foreground size-3.5' />}
              </li>
            );
          })}
        </ol>

        {/* 当前步骤表单 */}
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='flex items-center justify-between text-sm'>
              <span>
                Step {step}/7 · {ONBOARDING_STEPS[step - 1]}
              </span>
              {!currentComplete && step < 7 && (
                <span className='text-muted-foreground text-xs font-normal'>
                  完成必填项后可进入下一步
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className='p-4'>
            {step === 1 && (
              <OnboardingStepBasic
                value={draft.basic}
                onChange={(basic) => setDraft((prev) => ({ ...prev, basic }))}
              />
            )}
            {step === 2 && (
              <OnboardingStepTrust
                value={draft.trust}
                onChange={(trust) => setDraft((prev) => ({ ...prev, trust }))}
              />
            )}
            {step === 3 && (
              <OnboardingStepConnector
                value={draft.connector}
                onChange={(connector) => setDraft((prev) => ({ ...prev, connector }))}
              />
            )}
            {step === 4 && (
              <OnboardingStepManifest
                value={draft.manifestJson}
                onChange={(manifestJson) => setDraft((prev) => ({ ...prev, manifestJson }))}
              />
            )}
            {step === 5 && (
              <OnboardingStepFrontend
                value={draft.frontend}
                onChange={(frontend) => setDraft((prev) => ({ ...prev, frontend }))}
              />
            )}
            {step === 6 && (
              <OnboardingStepAgents
                value={draft.agents}
                onChange={(agents) => setDraft((prev) => ({ ...prev, agents }))}
                agentReleases={agentReleases}
                capabilityProfiles={capabilityProfiles}
                policies={policies}
                quotas={quotas}
                capabilityCeilings={capabilityCeilings}
              />
            )}
            {step === 7 && (
              <OnboardingStepPublish hostName={draft.basic.name} onPublished={onPublished} />
            )}
          </CardContent>
        </Card>

        {/* 底部导航 */}
        <div className='flex items-center justify-between gap-2'>
          <div className='flex gap-2'>
            <Button variant='outline' disabled={step === 1} onClick={() => goToStep(step - 1)}>
              <Icons.chevronLeft data-icon='inline-start' />
              上一步
            </Button>
            <Button variant='outline' onClick={saveAndExit}>
              保存并退出
            </Button>
          </div>
          {step < 7 && (
            <Button disabled={!canGoNext} onClick={next}>
              下一步
              <Icons.chevronRight data-icon='inline-end' />
            </Button>
          )}
        </div>
      </div>

      {/* 右侧检查清单 */}
      <Card className='h-fit py-0 lg:sticky lg:top-4'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='flex items-center gap-2 text-sm'>
            <Icons.forms className='size-4' />
            接入检查清单
          </CardTitle>
        </CardHeader>
        <CardContent className='divide-y p-0'>
          {ONBOARDING_STEPS.map((title, index) => (
            <div key={title} className='flex items-center justify-between gap-2 px-4 py-2.5'>
              <span className={cn('text-sm', done[index] ? 'font-medium' : 'text-muted-foreground')}>
                {index + 1}. {title}
              </span>
              {done[index] ? (
                <Icons.circleCheck className='text-emerald-600 size-4' />
              ) : (
                <Icons.circle className='text-muted-foreground/50 size-4' />
              )}
            </div>
          ))}
          <div className='bg-muted/40 px-4 py-2.5 text-xs'>
            已完成 {done.filter(Boolean).length}/7 · 草稿自动保存到浏览器本地
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
