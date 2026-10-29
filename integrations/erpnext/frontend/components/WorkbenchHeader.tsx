import React from 'react';
import { CaretRightIcon, ClockIcon, CollapseIcon, CloseIcon, ExpandIcon, GearIcon, InfoIcon, SidebarIcon } from './icons';

export type WorkbenchHeaderProps = {
  title: string;
  company: string;
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  approvalsCount: number;
  onApprovals: () => void;
  onResources: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onClose: () => void;
  approvalsExpanded: boolean;
};

/** Workspace header: breadcrumb + conversation title + live badges + view controls. */
export function WorkbenchHeader(props: WorkbenchHeaderProps) {
  return <header className="ze-heading">
    <div className="ze-heading-title">
      {!props.sidebarOpen && <button className="ze-icon-btn" aria-label="展开会话列表" onClick={props.onOpenSidebar}><SidebarIcon size={15} /></button>}
      <div>
        <span className="ze-breadcrumb">{props.company || 'ERP 工作台'} <CaretRightIcon size={10} /></span>
        <div className="ze-heading-name">
          <strong>{props.title}</strong>
          {props.approvalsCount > 0 && <span className="ze-badge ze-badge--warn"><ClockIcon size={12} />待确认 {props.approvalsCount}</span>}
        </div>
      </div>
    </div>
    <div className="ze-heading-actions">
      <button className={`ze-heading-action ${props.approvalsCount ? 'is-attention' : ''}`} aria-expanded={props.approvalsExpanded} onClick={props.onApprovals}>
        <ClockIcon size={13} />{props.approvalsCount ? `待审批 ${props.approvalsCount}` : '审批'}
      </button>
      <button className="ze-heading-action" aria-label="打开 Agent 设置" aria-expanded={props.onResourcesExpanded} onClick={props.onResources}><GearIcon size={13} />设置</button>
      <button className="ze-icon-btn" data-ze-fullscreen onClick={props.onToggleFullscreen} aria-label={props.fullscreen ? '退出全屏' : '全屏显示'} title={props.fullscreen ? '退出全屏（Esc）' : '全屏显示'}>
        {props.fullscreen ? <CollapseIcon size={15} /> : <ExpandIcon size={15} />}
      </button>
      <button className="ze-icon-btn" onClick={props.onClose} aria-label="关闭助手" title="关闭（Esc）"><CloseIcon size={15} /></button>
    </div>
  </header>;
}
