import React, { useEffect, useRef, useState } from 'react';
import { DotsIcon, PlusIcon, SearchIcon, SidebarIcon } from './icons';
import { ZEBRA_LOGO } from './logo';

export type SessionRow = { name: string; title?: string; modified?: string; creation?: string };
export type SessionGroup = { label: string; items: SessionRow[] };

export type SessionSidebarProps = {
  groups: SessionGroup[];
  selected: string;
  search: string;
  onSearch: (value: string) => void;
  onCreate: () => void;
  onSelect: (name: string) => void;
  onRename: (item: SessionRow) => void;
  onDelete: (item: SessionRow) => void;
  onCollapse: () => void;
  ageOf: (item: SessionRow) => number;
  company: string;
  companies: { name?: string }[] | undefined;
  onCompanyChange: (name: string) => void;
  controlDisabled: boolean;
  emptyHint: string;
};

/** Fullscreen session rail: brand, quick create/search, grouped history, tenant footer. */
export function SessionSidebar(props: SessionSidebarProps) {
  const disabled = props.controlDisabled;
  const [copiedId, setCopiedId] = useState('');
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (copiedTimer.current) clearTimeout(copiedTimer.current); }, []);
  function showCopied(name: string) {
    setCopiedId(name);
    if (copiedTimer.current) clearTimeout(copiedTimer.current);
    copiedTimer.current = setTimeout(() => setCopiedId(''), 1400);
  }
  const matched = (item: SessionRow) => String(item.title || '').toLocaleLowerCase().includes(props.search.toLocaleLowerCase());
  return <nav className="ze-sidebar" aria-label="会话列表">
    <header>
      <div className="ze-wordmark">
        <span className="ze-brand-mark"><img src={ZEBRA_LOGO} alt="" /></span>
        <h2>zebra</h2>
        <small>ERP AGENT</small>
      </div>
      <button aria-label="收起会话列表" title="收起会话列表" onClick={props.onCollapse}><SidebarIcon size={15} /></button>
    </header>
    <div className="ze-side-actions">
      <button className="ze-create" disabled={disabled} onClick={props.onCreate}>
        <PlusIcon size={14} /><span>新建协同对话</span>
      </button>
      <label className="ze-search">
        <SearchIcon size={13} />
        <input type="search" aria-label="搜索会话" placeholder="搜索单据、工作流、历史问答…" value={props.search} onChange={event => props.onSearch(event.target.value)} />
      </label>
    </div>
    <div className="ze-session-scroll">
      {props.groups.map(group => {
        const items = group.items.filter(matched);
        return items.length ? <section key={group.label}>
          <h3>{group.label}</h3>
          {items.map(item => <div key={item.name} className={`ze-session ${props.selected === item.name ? 'is-selected' : ''}`}>
            <button className="ze-session-select" disabled={disabled} aria-current={props.selected === item.name ? 'page' : undefined} onClick={() => props.onSelect(item.name)} title={item.title}>
              <strong>{item.title || '新会话'}</strong>
              <time>{formatAge(props.ageOf(item))}</time>
            </button>
            <details className="ze-session-menu">
              <summary aria-label={`管理会话：${item.title || '新会话'}`}><DotsIcon size={14} /></summary>
              <div>
                <button disabled={disabled} onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); props.onRename(item); }}>重命名</button>
                <button onClick={() => { void copySessionId(item.name).then(() => showCopied(item.name)); }}>{copiedId === item.name ? '已复制' : '复制会话 ID'}</button>
                <button disabled={disabled} onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); props.onDelete(item); }}>删除</button>
              </div>
            </details>
          </div>)}
        </section> : null;
      })}
      {!props.groups.some(group => group.items.some(matched)) && <p className="ze-session-empty">{props.search ? '没有匹配的会话' : props.emptyHint}</p>}
    </div>
    <footer className="ze-company">
      <label>
        <span>公司账套</span>
        <select aria-label="公司" value={props.company} disabled={disabled} onChange={event => props.onCompanyChange(event.target.value)}>
          {(props.companies || []).map((item: any) => <option key={item.name || item} value={item.name || item}>{item.name || item}</option>)}
        </select>
      </label>
      <small>操作由你把控，写入需确认。</small>
    </footer>
  </nav>;
}

export function formatAge(hours: number) {
  if (!Number.isFinite(hours)) return '';
  if (hours < 1) return '刚刚';
  if (hours < 24) return `${Math.floor(hours)} 小时前`;
  if (hours < 168) return `${Math.floor(hours / 24)} 天前`;
  return `${Math.floor(hours / 168)} 周前`;
}

async function copySessionId(name: string) {
  // Clipboard API first (HTTPS desk), execCommand fallback for older embeds.
  // Never throws: a failed copy simply leaves the label unchanged.
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(name); return; }
  } catch { /* fall through to the legacy path */ }
  try {
    const focused = document.activeElement;
    const node = document.createElement('textarea');
    node.value = name; node.style.position = 'fixed'; node.style.opacity = '0';
    document.body.appendChild(node); node.select();
    document.execCommand('copy');
    node.remove();
    if (focused instanceof HTMLElement) focused.focus({ preventScroll: true });
  } catch { /* keep silent; the label stays as-is */ }
}
