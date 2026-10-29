import React,{useState,useRef,useEffect} from 'react';

const names:any={business:'业务查询与审批',research:'联网研究',analysis:'联网与文件分析'};

export function CapabilityControls({conversation,catalog,api,onError}:any) {
  const [profile,setProfile]=useState(catalog.capability_profile||'business'),[skills,setSkills]=useState<any[]>([]),[mcp,setMcp]=useState<any[]>([]),[selection,setSelection]=useState<any>(catalog.extension_selection||{}),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[endpoint,setEndpoint]=useState(''),[skillId,setSkillId]=useState(''),[versionId,setVersionId]=useState(''),[authMode,setAuthMode]=useState('none'),[credentialRow,setCredentialRow]=useState<any>(null),[token,setToken]=useState('');
  const gate=useRef(false),key=useRef(''),requestBody=useRef(''),upload=useRef<HTMLInputElement>(null);
  const enabled=catalog.groups?.find((g:any)=>g.id==='extensions')?.status==='available';
  async function run(work:()=>Promise<any>) {if(gate.current)return;gate.current=true;setBusy(true);setNotice('');try{await work();}catch(e){onError(e);}finally{gate.current=false;setBusy(false);}}
  async function load() {const [a,b]=await Promise.all([api('extension_inventory',{conversation,kind:'skills'}),api('extension_inventory',{conversation,kind:'mcp'})]);setSkills(a.items||[]);setMcp(b.items||[]);}
  function choose(kind:string,id:string,checked:boolean) {setSelection((old:any)=>({...old,[kind]:checked?[...(old[kind]||[]),id]:(old[kind]||[]).filter((v:string)=>v!==id)}));}
  async function toggle(kind:string,row:any) {await api('extension_toggle',{conversation,kind,item:row.installation_id||row.connection_id,expected_revision:row.revision,enabled:!row.enabled});await load();}
  async function save(){await api('configure_capabilities',{conversation,capability_profile:profile,selection:JSON.stringify(selection)});setNotice('已保存；将按此能力组合创建本会话任务。');}
  async function create(kind:string) {const fingerprint=JSON.stringify([kind,endpoint,authMode,skillId,versionId]);if(requestBody.current!==fingerprint){requestBody.current=fingerprint;key.current='';}if(!key.current)key.current=crypto.randomUUID();await api('extension_create',{conversation,kind,request_id:key.current,...(kind==='mcp'?{endpoint,auth_mode:authMode}:{skill_id:skillId,version_id:versionId})});key.current='';setEndpoint('');await load();}
  async function importSkill(file:File) {if(!file.size||file.size>10485760)throw Error('Skill 安装包须小于 10 MiB');const bytes=new Uint8Array(await file.arrayBuffer());const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));await api('skill_import',{conversation,request_id:'skill-'+digest,content_base64:btoa(binary)});await load();}
  useEffect(()=>{if(enabled)void run(load);},[conversation]);
  return <section className="ze-set">
    <div className="ze-set-block">
      <div className="ze-set-block-head"><h4>能力组合</h4><p>保存后新任务按此组合创建；已运行任务权限不变。</p></div>
      <div className="ze-set-inline">
        <select className="ze-set-select" disabled={busy||catalog.capabilities_locked} value={profile} onChange={e=>setProfile(e.target.value)}>{(catalog.capability_profiles||['business']).map((p:string)=><option key={p} value={p}>{names[p]||p}</option>)}</select>
        <button className="ze-btn-primary" disabled={busy||catalog.capabilities_locked} onClick={()=>void run(save)}>保存组合</button>
      </div>
      {catalog.capabilities_locked&&<p className="ze-set-note">此会话能力已固定。新建会话可调整；已运行任务的权限不会扩大。</p>}
      {notice&&<p className="ze-set-ok" role="status">{notice}</p>}
    </div>
    {!enabled
      ? <p className="ze-set-note">此会话当前运行时尚未开放技能与连接管理。</p>
      : <div className="ze-set-block">
        <div className="ze-set-block-head"><h4>工具与连接</h4><p>Skill 与 MCP 连接的启用、凭据与目录。</p>
          <div className="ze-set-block-actions"><button className="ze-btn" disabled={busy} onClick={()=>void run(load)}>刷新</button></div>
        </div>
        <h5 className="ze-set-sub">Skill（{skills.length}）</h5>
        {skills.length?<ul className="ze-set-rows">{skills.map(row=><li key={row.installation_id} className="ze-set-row">
          <label className="ze-set-check"><input type="checkbox" disabled={busy||catalog.capabilities_locked||!row.enabled} checked={(selection.skills||[]).includes(row.installation_id)} onChange={e=>choose('skills',row.installation_id,e.target.checked)}/><span className="ze-set-row-title">{row.name||row.version?.skill_id}</span></label>
          <span className={`ze-badge ${row.enabled?'ze-badge--ok':'ze-badge--neutral'}`}>{row.enabled?'已启用':'已停用'}</span>
          <button className="ze-btn" disabled={busy||row.managed} onClick={()=>void run(()=>toggle('skills',row))}>{row.enabled?'停用':'启用'}</button>
        </li>)}</ul>:<p className="ze-set-empty">尚未安装 Skill；可从插件市场安装或导入安装包。</p>}
        <h5 className="ze-set-sub">MCP 连接（{mcp.length}）</h5>
        {mcp.length?<ul className="ze-set-rows">{mcp.map(row=><li key={row.connection_id} className="ze-set-row ze-set-row--wrap">
          <label className="ze-set-check"><input type="checkbox" disabled={busy||catalog.capabilities_locked||!row.enabled||!row.selectable} checked={(selection.mcp||[]).includes(row.connection_id)} onChange={e=>choose('mcp',row.connection_id,e.target.checked)}/><span className="ze-set-row-title" title={row.endpoint}>{row.endpoint}</span></label>
          <span className="ze-set-meta">{row.selectable?`${row.tool_count} 项工具`:'目录尚未就绪'}</span>
          <div className="ze-set-row-actions">
            <button className="ze-btn" disabled={busy} onClick={()=>void run(()=>toggle('mcp',row))}>{row.enabled?'停用':'启用'}</button>
            {row.auth_mode==='bearer'&&<button className="ze-btn" disabled={busy} onClick={()=>{setCredentialRow(row);setToken('');}}>设置凭据</button>}
            <button className="ze-btn" disabled={busy} onClick={()=>void run(async()=>{await api('extension_refresh',{conversation,item:row.connection_id,expected_revision:row.revision});await load();})}>刷新目录</button>
          </div>
        </li>)}</ul>:<p className="ze-set-empty">尚未添加 MCP 连接。</p>}
        {credentialRow&&<form className="ze-set-form ze-set-form--card" onSubmit={e=>{e.preventDefault();const value=token,row=credentialRow;setToken('');void run(async()=>{await api('extension_credentials',{conversation,item:row.connection_id,expected_revision:row.revision,token:value});setCredentialRow(null);await load();});}}><label>MCP 访问令牌<input type="password" autoComplete="new-password" value={token} onChange={e=>setToken(e.target.value)} maxLength={4096}/></label><div className="ze-set-inline"><button className="ze-btn-primary" disabled={busy||!token} type="submit">保存凭据</button><button className="ze-btn" type="button" disabled={busy} onClick={()=>{setCredentialRow(null);setToken('');}}>取消</button></div></form>}
        <div className="ze-set-inline ze-set-inline--gap">
          <input type="file" ref={upload} accept=".zip" hidden onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void run(()=>importSkill(file));}}/>
          <button className="ze-btn" disabled={busy} onClick={()=>upload.current?.click()}>导入 Skill 安装包</button>
        </div>
        <details className="ze-set-details"><summary>添加 MCP 连接或安装已发布 Skill</summary>
          <div className="ze-set-form">
            <label>MCP 服务地址<input value={endpoint} onChange={e=>setEndpoint(e.target.value)} type="url" placeholder="https://…"/></label>
            <label>认证方式<select className="ze-set-select" value={authMode} onChange={e=>setAuthMode(e.target.value)}><option value="none">无需凭据</option><option value="bearer">访问令牌</option></select></label>
            <button className="ze-btn" disabled={busy||!endpoint} onClick={()=>void run(()=>create('mcp'))}>添加 MCP</button>
            <p className="ze-set-note">添加不会自动连接。启用后，由你主动刷新目录。</p>
            <label>已发布 Skill 标识<input value={skillId} onChange={e=>setSkillId(e.target.value)}/></label>
            <label>版本<input value={versionId} onChange={e=>setVersionId(e.target.value)}/></label>
            <button className="ze-btn" disabled={busy||!skillId||!versionId} onClick={()=>void run(()=>create('skills'))}>安装 Skill</button>
          </div>
        </details>
      </div>}
  </section>;
}
