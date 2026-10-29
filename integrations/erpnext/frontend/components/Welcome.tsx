import React from 'react';
import { ZEBRA_LOGO } from './logo';

export type WelcomeAction = { label: string; prompt: string };

/** Empty-state greeting with contextual quick-start pills. */
export function Welcome({ actions, onPick, disabled, notice }: { actions: WelcomeAction[]; onPick: (prompt: string) => void; disabled?: boolean; notice?: string }) {
  return <div className="ze-welcome">
    <span className="ze-welcome-mark"><img src={ZEBRA_LOGO} alt="" /></span>
    <h2>今天需要处理什么？</h2>
    <p>查询业务数据、分析报表，或准备单据操作。<br />需要修改数据时，会先展示具体操作供你确认。</p>
    {notice && <p className="ze-welcome-notice">{notice}</p>}
    {actions.length > 0 && <div className="ze-welcome-pills">
      {actions.map((item: any) => <button key={item.id || item.label} disabled={disabled} onClick={() => onPick(item.prompt)}>
        <span aria-hidden="true">{item.emoji || '✦'}</span>{item.label}
      </button>)}
    </div>}
  </div>;
}
