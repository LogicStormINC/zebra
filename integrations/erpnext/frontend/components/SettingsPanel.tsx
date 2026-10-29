import React, { useEffect, useRef, useState } from 'react';
import { PluginPanel } from './PluginPanel';
import { PuzzleIcon, PlugIcon, SlidersIcon, BookIcon, ClockIcon, ListIcon, InfoIcon } from './icons';
import { CapabilityControls } from '../capability-controls';
import { KnowledgeControls } from '../knowledge-controls';
import { ScheduleControls } from '../schedule-controls';
import { HistoricalArtifacts } from '../historical-artifacts';

export type SettingsPanelProps = {
  conversation: string;
  catalog: any;
  artifacts: any;
  api: any;
  onError: (error: unknown) => void;
  onNew: () => void;
  page: { route: string[]; doctype: string | null; name: string | null };
};

const TABS = [
  { id: 'plugins', label: '插件', icon: PuzzleIcon },
  { id: 'tools', label: '工具与连接', icon: PlugIcon },
  { id: 'files', label: '文件存储', icon: ListIcon },
  { id: 'knowledge', label: '知识与记忆', icon: BookIcon },
  { id: 'schedules', label: '定时任务', icon: ClockIcon },
  { id: 'capability', label: '能力', icon: SlidersIcon },
  { id: 'page', label: '页面信息', icon: InfoIcon },
] as const;

/**
 * Trench-parity agent settings: tabbed console over the already-wired native
 * capability RPCs. Feature tabs render only what the conversation's runtime
 * actually supports; unsupported states are disclosed honestly.
 */
export function SettingsPanel(props: SettingsPanelProps) {
  const [tab, setTab] = useState<string>('plugins');
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => { scrollRef.current?.scrollTo({ top: 0 }); }, [tab]);
  const { conversation, catalog } = props;
  const full = !!conversation && catalog?.runtime_release === 'cloud114';
  const unsupported = (what: string) => <p className="ze-settings-empty">此会话当前运行时暂不支持{what}；新会话将按最新运行时开放。</p>;
  return <div className="ze-settings">
    <nav className="ze-settings-tabs" role="tablist" aria-label="Agent 设置">
      {TABS.map(item => <button key={item.id} role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)}>
        <item.icon size={13} />{item.label}
      </button>)}
    </nav>
    <div className="ze-settings-body" ref={scrollRef}>
      {tab === 'plugins' && (full ? <PluginPanel conversation={conversation} api={props.api} onError={props.onError} /> : unsupported('插件管理'))}
      {tab === 'tools' && (full
        ? <CapabilityLazy conversation={conversation} catalog={catalog} api={props.api} onError={props.onError} />
        : unsupported('技能与连接管理'))}
      {tab === 'files' && (conversation
        ? <ArtifactsLazy conversation={conversation} catalog={catalog} artifacts={props.artifacts} api={props.api} onError={props.onError} />
        : <p className="ze-settings-empty">发送消息后可查看任务成果。</p>)}
      {tab === 'knowledge' && (full
        ? <KnowledgeLazy conversation={conversation} catalog={catalog} api={props.api} onError={props.onError} />
        : unsupported('知识资料与记忆'))}
      {tab === 'schedules' && (full
        ? <ScheduleLazy conversation={conversation} catalog={catalog} api={props.api} onError={props.onError} />
        : unsupported('定时任务'))}
      {tab === 'capability' && <CapabilityStatus catalog={catalog} onNew={props.onNew} />}
      {tab === 'page' && <PageInfo props={props} />}
    </div>
  </div>;
}

function CapabilityStatus({ catalog, onNew }: any) {
  const labels: any = { partial: '部分可用', available: '可使用', configured: '已配置', needs_configuration: '需配置', unavailable: '不可用', restricted: '当前不可用', not_implemented: '待实现', pending: '待验收' };
  return <section className="ze-settings-section">
    <h3>能力状态</h3>
    {!catalog ? <p className="ze-settings-empty">正在读取能力状态…</p> : <>
      <ul className="ze-capabilities">{(catalog.groups || []).map((group: any) => <li key={group.id}><strong>{group.label}</strong><span>{labels[group.status] || group.status}</span><p>{group.reason}</p></li>)}</ul>
      {catalog.legacy_workspace && <p className="ze-settings-empty">此历史会话使用旧共享工作区，不能上传私人附件。<button className="ze-chip-btn" onClick={onNew}>新建会话</button></p>}
    </>}
  </section>;
}

function PageInfo({ props }: any) {
  const { page } = props;
  return <section className="ze-settings-section">
    <h3>当前页面</h3>
    <p className="ze-settings-page">当前页面 · {page.doctype ? `${page.doctype} / ${page.name}` : page.route.join(' / ') || '工作台'}</p>
    {page.doctype && !(window as any).cur_frm?.set_value && <p className="ze-settings-empty">当前页面尚不支持安全填写；可以查询业务或准备单据变更。</p>}
    {location.protocol !== 'https:' && <p className="ze-settings-empty">页面操作需要 HTTPS；聊天与业务查询仍可使用。</p>}
    <p className="ze-settings-empty">{props.catalog?.private_uploads ? '支持私人附件，可使用输入框附件按钮（最多 4 个）。' : '此会话暂不支持私人附件。'}</p>
  </section>;
}

// The tabs reuse the exact production controls from the ERP capability work;
// each control owns its styled blocks under the shared .ze-set design system.
const CapabilityLazy = (p: any) => <CapabilityControls {...p} />;
const KnowledgeLazy = (p: any) => <KnowledgeControls {...p} />;
const ScheduleLazy = (p: any) => <ScheduleControls {...p} />;
const ArtifactsLazy = (p: any) => <HistoricalArtifacts {...p} />;
