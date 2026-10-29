import React, { useEffect, useRef, useState } from 'react';
import { PuzzleIcon, RefreshIcon, SearchIcon } from './icons';

const pluginError = (error: any) => {
  const status = typeof error?.status === 'number' ? error.status : 0;
  if (status === 403) return '当前账号没有管理此插件的权限。';
  if (status === 404) return '插件服务未开放，或该插件当前不可访问。';
  if (status === 409) return '配置已变化，请重新加载；若插件所需服务尚未就绪，请先完成服务授权。';
  if (status === 422) return '此插件当前无法安装，请联系管理员检查已批准的插件包。';
  const message = error instanceof Error ? error.message : '';
  if (message.includes('404')) return '插件服务在当前 Agent 运行时版本暂未开放；运行时升级后即可在此安装与管理插件。';
  return message || '操作未确认完成，请重新加载核对状态；操作不会自动重试。';
};

/**
 * Plugin console: approved market packages plus installed plugin management.
 * Installs use a digest-derived stable request id so an uncertain response can
 * be retried safely without duplicate installations.
 */
export function PluginPanel({ conversation, api, onError }: { conversation: string; api: any; onError: (error: unknown) => void }) {
  const [view, setView] = useState<'market' | 'installed'>('market');
  return <section className="ze-plugins" aria-label="插件管理">
    <header className="ze-plugins-head">
      <h3>插件</h3>
      <p>从市场一键安装已批准的能力包，或管理已安装插件。</p>
    </header>
    <div role="tablist" aria-label="插件视图" className="ze-segmented">
      <button role="tab" aria-selected={view === 'market'} onClick={() => setView('market')}>插件市场</button>
      <button role="tab" aria-selected={view === 'installed'} onClick={() => setView('installed')}>已安装</button>
    </div>
    {view === 'market'
      ? <PluginMarket conversation={conversation} api={api} onError={onError} onInstalled={() => setView('installed')} />
      : <PluginInstalled conversation={conversation} api={api} onError={onError} onBrowse={() => setView('market')} />}
    <p className="ze-plugins-note">启用状态只管理能力包的可用性，不会授予额外数据访问权限；具体任务仍受原有授权约束。</p>
  </section>;
}

function PluginMarket({ conversation, api, onError, onInstalled }: any) {
  const [items, setItems] = useState<any[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [installing, setInstalling] = useState('');
  const [error, setError] = useState(''), [query, setQuery] = useState('');
  const alive = useRef(true), inFlight = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function load(more = false) {
    if (inFlight.current) return;
    inFlight.current = true; setLoading(true); setError('');
    try {
      const data = await api('plugin_market', more ? { conversation, cursor } : { conversation });
      if (!alive.current) return;
      const page = data.items || [];
      setItems(old => more ? [...new Map([...old, ...page].map(item => [item.package_digest, item])).values()] : page);
      setCursor(data.next_cursor || null);
    } catch (cause) { if (alive.current) setError(pluginError(cause)); }
    finally { inFlight.current = false; if (alive.current) setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  async function install(item: any) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setInstalling(item.package_digest); setError('');
    try {
      // Stable digest-scoped id: retries and refreshes reuse the same server intent.
      await api('plugin_install', { conversation, package_digest: item.package_digest, request_id: `market-${item.package_digest}` });
      if (alive.current) onInstalled();
    } catch (cause) { if (alive.current) setError(pluginError(cause)); }
    finally { inFlight.current = false; setBusy(false); if (alive.current) setInstalling(''); }
  }
  const needle = query.trim().toLocaleLowerCase();
  const visible = items.filter(item => `${item.plugin_id} ${item.publisher}`.toLocaleLowerCase().includes(needle));
  return <div className="ze-plugins-body">
    <div className="ze-plugins-toolbar">
      <label className="ze-plugins-search"><SearchIcon size={13} /><input type="search" aria-label="搜索市场插件" placeholder="搜索名称或发布者" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <button className="ze-chip-btn" disabled={loading || busy} onClick={() => void load()}><RefreshIcon size={12} />刷新</button>
    </div>
    <p className="ze-plugins-hint">一键安装已批准的插件，系统自动准备所需组件；安装后可在“已安装”中启用。</p>
    {error && <p className="ze-plugins-error" role="alert">{error}</p>}
    {loading && !items.length ? <p className="ze-plugins-status" role="status">正在加载插件市场…</p>
      : !error && !items.length ? <div className="ze-plugins-empty"><PuzzleIcon size={26} /><h4>市场暂未发布插件</h4><p>管理员批准能力包后，会在这里展示。</p></div>
      : <ul className="ze-plugin-list">
        {visible.map(item => <li key={item.package_digest}>
          <span className="ze-plugin-icon"><PuzzleIcon size={18} /></span>
          <span className="ze-plugin-info"><strong>{item.plugin_id}</strong><small>{item.publisher} · {item.version}</small><small className="ze-plugin-kinds">{(item.components || []).map((c: any) => c.kind === 'skill-bundle' ? 'Skill' : 'MCP').filter((kind: string, index: number, all: string[]) => all.indexOf(kind) === index).join(' + ')}</small></span>
          <button className="ze-chip-btn" disabled={busy || !!installing} aria-label={`安装 ${item.plugin_id}`} onClick={() => void install(item)}>{installing === item.package_digest ? '安装中…' : '安装'}</button>
        </li>)}
      </ul>}
    {!loading && items.length > 0 && !visible.length && <p className="ze-plugins-status" role="status">{cursor ? '已加载结果中没有匹配项，可加载更多后继续查找。' : '没有匹配的插件。'}</p>}
    {cursor && <button className="ze-chip-btn" disabled={loading || busy} onClick={() => void load(true)}>加载更多</button>}
  </div>;
}

function PluginInstalled({ conversation, api, onError, onBrowse }: any) {
  const [items, setItems] = useState<any[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [query, setQuery] = useState(''), [filter, setFilter] = useState('all');
  const alive = useRef(true), inFlight = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function load(more = false) {
    if (inFlight.current) return;
    inFlight.current = true; setLoading(true); setError('');
    try {
      const data = await api('plugin_inventory', more ? { conversation, cursor } : { conversation });
      if (!alive.current) return;
      const page = data.items || [];
      setItems(old => more ? [...new Map([...old, ...page].map(item => [item.installation_id, item])).values()] : page);
      setCursor(data.next_cursor || null);
    } catch (cause) { if (alive.current) setError(pluginError(cause)); }
    finally { inFlight.current = false; if (alive.current) setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  async function toggle(item: any) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await api('plugin_toggle', { conversation, installation: item.installation_id, expected_revision: item.revision, enabled: !item.enabled });
      if (alive.current) {
        setItems(old => old.map(entry => entry.installation_id === item.installation_id ? { ...entry, enabled: !entry.enabled, revision: (entry.revision || 0) + 1 } : entry));
        setNotice(`${item.plugin_id} 已${!item.enabled ? '启用' : '停用'}。`);
      }
    } catch (cause) { if (alive.current) { setError(pluginError(cause)); void load(); } }
    finally { inFlight.current = false; if (alive.current) setBusy(false); }
  }
  const needle = query.trim().toLocaleLowerCase();
  const visible = items.filter(item => (filter === 'all' || item.enabled === (filter === 'enabled')) && `${item.plugin_id} ${item.publisher}`.toLocaleLowerCase().includes(needle));
  return <div className="ze-plugins-body">
    <div className="ze-plugins-toolbar">
      <label className="ze-plugins-search"><SearchIcon size={13} /><input type="search" aria-label="搜索已安装插件" placeholder="搜索名称或发布者" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <select aria-label="插件状态" value={filter} onChange={event => setFilter(event.target.value)}>
        <option value="all">全部状态</option><option value="enabled">已启用</option><option value="disabled">已停用</option>
      </select>
      <button className="ze-chip-btn" disabled={loading || busy} onClick={() => void load()}><RefreshIcon size={12} />刷新</button>
    </div>
    <p className="ze-plugins-count">已安装 {items.length} · 已启用 {items.filter(item => item.enabled).length}</p>
    {error && <p className="ze-plugins-error" role="alert">{error}</p>}
    {notice && <p className="ze-plugins-status" role="status">{notice}</p>}
    {loading && !items.length ? <p className="ze-plugins-status" role="status">正在加载已安装插件…</p>
      : !error && !items.length ? <div className="ze-plugins-empty"><PuzzleIcon size={26} /><h4>还没有安装插件</h4><p>从市场一键安装，所需组件由系统准备。</p><button className="ze-chip-btn" onClick={onBrowse}>浏览插件市场</button></div>
      : <ul className="ze-plugin-list">
        {visible.map(item => <li key={item.installation_id}>
          <span className={`ze-plugin-icon ${item.enabled ? 'is-on' : ''}`}><PuzzleIcon size={18} /></span>
          <span className="ze-plugin-info"><strong>{item.plugin_id}</strong><small>{item.publisher} · {item.version}</small><small>{(item.bindings || []).length} 个组件{item.bindings?.some?.((b: any) => b.kind === 'mcp-http') ? ' · 含 MCP' : ''}</small></span>
          <span className={`ze-badge ${item.enabled ? 'ze-badge--ok' : 'ze-badge--neutral'}`}>{item.enabled ? '已启用' : '已停用'}</span>
          <button className="ze-chip-btn" disabled={busy} onClick={() => void toggle(item)}>{item.enabled ? '停用' : '启用'}</button>
        </li>)}
      </ul>}
    {!loading && items.length > 0 && !visible.length && <p className="ze-plugins-status" role="status">{cursor ? '已加载的插件中没有匹配项，可加载更多后继续查找。' : '没有匹配的插件，试试其他筛选条件。'}</p>}
    {cursor && <button className="ze-chip-btn" disabled={busy || loading} onClick={() => void load(true)}>加载更多</button>}
  </div>;
}
