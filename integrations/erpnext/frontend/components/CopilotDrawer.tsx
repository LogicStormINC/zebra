import React from 'react';
import { CaretDownIcon, ClockIcon, CloseIcon, ExpandIcon, GearIcon, PlusIcon } from './icons';

export type CopilotDrawerProps = {
  selected: string;
  sessions: { name: string; title?: string }[];
  onSessionChange: (name: string) => void;
  company: string;
  companies: { name?: string }[] | undefined;
  onCompanyChange: (name: string) => void;
  onNew: () => void;
  controlDisabled: boolean;
  enabled: boolean | undefined;
  paused: boolean | undefined;
  pageLabel: string;
  onExpand: () => void;
  onClose: () => void;
  onSettings: () => void;
  approvalsCount: number;
  onApprovals: () => void;
  children: React.ReactNode;
};

/**
 * Floating copilot drawer shell for everyday ERP pages: a rounded card hovering
 * over the desk with tenant/session controls on top and a live ERP status line.
 * Purely presentational — every action arrives as a prop callback.
 */
export function CopilotDrawer(props: CopilotDrawerProps) {
  const current = props.sessions.find(item => item.name === props.selected);
  return <>
    <header className="ze-drawer-head">
      <div className="ze-drawer-head-row">
        <label className="ze-select-pill ze-select-pill--session">
          <SessionSelect sessions={props.sessions} selected={props.selected} onChange={props.onSessionChange} disabled={props.controlDisabled} />
        </label>
        <label className="ze-select-pill">
          <select aria-label="公司" value={props.company} disabled={props.controlDisabled} onChange={event => props.onCompanyChange(event.target.value)}>
            {(props.companies || []).map((item: any) => <option key={item.name || item} value={item.name || item}>{item.name || item}</option>)}
          </select>
          <CaretDownIcon className="ze-select-pill-caret" size={12} />
        </label>
        <button className="ze-chip-btn" disabled={props.controlDisabled} onClick={props.onNew}><PlusIcon size={13} />新建</button>
        <span className="ze-drawer-head-spacer" />
        {props.approvalsCount > 0 && <button className="ze-chip-btn ze-chip-btn--attention" aria-label="打开待确认操作" onClick={props.onApprovals}><ClockIcon size={12} />{props.approvalsCount}</button>}
        <button className="ze-icon-btn" aria-label="打开 Agent 设置" title="Agent 设置" onClick={props.onSettings}><GearIcon size={15} /></button>
        <button className="ze-icon-btn" data-ze-fullscreen onClick={props.onExpand} aria-label="全屏工作台" title="全屏工作台"><ExpandIcon size={15} /></button>
        <button className="ze-icon-btn" onClick={props.onClose} aria-label="关闭助手" title="关闭（Esc）"><CloseIcon size={15} /></button>
      </div>
      <div className="ze-drawer-status">
        <span className="ze-status-item">
          <span className={`ze-dot ${props.paused ? '' : 'ze-dot--pulse'}`} style={props.paused ? { background: '#f59e0b' } : undefined} />
          <span className="ze-status-text">{props.paused ? 'Agent 维护中，暂不接受新提交' : props.enabled ? 'ERP 服务已就绪' : 'zebra 服务未启用'}</span>
        </span>
        <span className="ze-status-page" title={props.pageLabel}>当前：{current?.title ? `${current.title} · ` : ''}{props.pageLabel}</span>
      </div>
    </header>
    {props.children}
  </>;
}

function SessionSelect({ sessions, selected, onChange, disabled }: any) {
  return <select aria-label="会话" value={selected} disabled={disabled} onChange={event => onChange(event.target.value)}>
    {!sessions.length && <option value="">新会话</option>}
    {sessions.map(item => <option key={item.name} value={item.name}>{item.title || '新会话'}</option>)}
  </select>;
}
