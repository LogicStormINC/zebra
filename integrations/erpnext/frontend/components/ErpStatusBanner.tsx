import React from 'react';
import { ShieldIcon } from './icons';

/** One-line ERP connection strip shown above the conversation canvas. */
export function ErpStatusBanner({ enabled, paused, company, pageLabel }: { enabled: boolean | undefined; paused: boolean | undefined; company: string; pageLabel: string }) {
  const state = paused ? { tone: 'warn' as const, text: 'Agent 维护中，暂不接受新提交' }
    : enabled ? { tone: 'ok' as const, text: 'ERP 服务已就绪' }
    : { tone: 'neutral' as const, text: 'zebra 服务未启用' };
  return <div className="ze-erp-status" role="status">
    <span className="ze-erp-status-left">
      <span className={`ze-dot ${state.tone === 'ok' ? 'ze-dot--pulse' : ''}`}
        style={state.tone === 'warn' ? { background: '#f59e0b' } : state.tone === 'neutral' ? { background: '#94a3b8' } : undefined} />
      <strong>{state.text}</strong>
      {company && <><span className="ze-erp-status-sep">·</span><span>账套：{company}</span></>}
    </span>
    <span className="ze-erp-status-right" title={pageLabel}><ShieldIcon size={12} />{pageLabel}</span>
  </div>;
}
