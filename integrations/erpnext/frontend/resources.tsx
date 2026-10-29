import React, { useEffect, useState, useRef } from 'react';
import { AgentArtifacts, AgentAssetPreview } from '@zebra-agent/react';
import { ScheduleControls } from './schedule-controls';
import { CapabilityControls } from './capability-controls';
import { KnowledgeControls } from './knowledge-controls';
import { HistoricalArtifacts } from './historical-artifacts';
import { artifactDownloadUrl, fileArtifacts, safePreviewMime } from './protocol.mjs';

export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  try { link.href = url; link.download = name; document.body.appendChild(link); link.click(); }
  finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
}
export function FileCard({conversation,artifact,onOpen,segmentId=''}:any) {
  const [status,setStatus]=useState(''), gate=useRef(false), alive=useRef(true), abort=useRef<AbortController|null>(null);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;abort.current?.abort();};},[]);
  const file=artifact.delivery||{}, ready=artifact.access?.allowed===true&&['ok','ready','available','payload_available'].includes(artifact.retrieval?.status);
  async function download() {
    if(gate.current||!ready)return;gate.current=true;setStatus('downloading');
    const controller=new AbortController();abort.current=controller;
    try {
      const response=await fetch(artifactDownloadUrl(conversation,artifact.artifact_id,segmentId),{credentials:'same-origin',signal:controller.signal});
      if(!response.ok||!response.headers.get('content-type')?.startsWith('application/octet-stream'))throw Error('下载失败');
      const blob=await response.blob();if(blob.size>20971520||(Number.isSafeInteger(file.size_bytes)&&blob.size!==file.size_bytes))throw Error('文件大小校验失败');
      if(alive.current){downloadBlob(blob,file.file_name);setStatus('');}
    }catch {if(alive.current)setStatus('error');}finally{gate.current=false;}
  }
  const size=Number.isSafeInteger(file.size_bytes)?file.size_bytes<1024?`${file.size_bytes} B`:file.size_bytes<1048576?`${(file.size_bytes/1024).toFixed(1)} KB`:`${(file.size_bytes/1048576).toFixed(1)} MB`:'大小未知';
  return <div className="ze-file-card"><span className="ze-file-icon" aria-hidden>▤</span><span className="ze-file-info"><strong>{file.file_name}</strong><small>{size} · {status==='error'?'下载失败，请重试':ready?'文件已生成':'文件当前不可用'}</small></span><button disabled={!ready||status==='downloading'} onClick={onOpen} aria-label={`预览 ${file.file_name}`}>预览</button><button className="ze-file-download" disabled={!ready||status==='downloading'} onClick={()=>void download()} aria-label={`下载 ${file.file_name}`}>{status==='downloading'?'下载中':status==='error'?'重试':'下载'}</button></div>;
}
export function ResourceFiles({ conversation, artifacts, api, onError, inline=false, openedId='', onPreviewed, segmentId='' }: any) {
  const [opened, setOpened] = useState<any>(null), [loading, setLoading] = useState(false);
  const previewUrl = useRef(''), generation = useRef(0);
  function close() { generation.current += 1; if (previewUrl.current) URL.revokeObjectURL(previewUrl.current); previewUrl.current = ''; setOpened(null); }
  useEffect(() => () => { generation.current += 1; if (previewUrl.current) URL.revokeObjectURL(previewUrl.current); }, []);
  useEffect(() => { close(); setLoading(false); }, [conversation]);
  useEffect(()=>{if(openedId){void open(openedId);onPreviewed?.();}},[openedId]);
  const rows = fileArtifacts(artifacts?.artifacts);
  async function open(id: string) {
    close(); const at = generation.current; setLoading(true);
    try {
      const detail = await api('artifact_detail', { conversation, artifact_id: id, ...(segmentId?{segment_id:segmentId}:{}) });
      const artifact = detail.artifact;
      if (at !== generation.current) return;
      const safeMime = safePreviewMime(artifact.delivery?.file_name, artifact.delivery?.mime_type);
      if (!safeMime) { setOpened({ ...artifact, previewUnavailable: true }); return; }
      const content = await api('artifact_content', { conversation, artifact_id: id, ...(segmentId?{segment_id:segmentId}:{}) });
      if (at !== generation.current) return;
      if (content.status !== 'ok' || content.encoding !== 'base64' || !Number.isSafeInteger(content.size_bytes) || content.size_bytes > 20971520 || typeof content.content_base64 !== 'string' || content.content_base64.length > 27962028) throw new Error('成果超过预览限制或内容不可用，请下载查看');
      const raw = atob(content.content_base64), bytes = Uint8Array.from(raw, char => char.charCodeAt(0));
      if (bytes.length !== content.size_bytes) throw new Error('成果内容大小无效');
      if (safePreviewMime(content.file_name || artifact.delivery.file_name, content.media_type) !== safeMime) throw new Error('成果类型与文件名不匹配；请下载查看');
      previewUrl.current = URL.createObjectURL(new Blob([bytes], { type: safeMime }));
      setOpened({ ...artifact, previewUrl: previewUrl.current });
    } catch (error) { if (at === generation.current) onError(error); }
    finally { if (at === generation.current) setLoading(false); }
  }
  if (inline && !rows.length && !openedId && !opened && !loading) return null;
  return <section className={inline?'ze-inline-files':'ze-artifact-gallery'} aria-label="当前任务成果">
    {inline?<><h4>当前任务成果</h4><p className="ze-resource-scope">所选任务分段的文件；未关联到某条回答。可在资源面板切换历史分段。</p>{rows.map((artifact:any)=><FileCard key={artifact.artifact_id} conversation={conversation} artifact={artifact} segmentId={segmentId} onOpen={()=>void open(artifact.artifact_id)}/>)}{!rows.length&&<p className="ze-resource-scope">当前任务分段暂无可展示的交付文件。</p>}</>:<><p>成果范围：当前任务分段。可在资源面板切换历史分段。</p><AgentArtifacts artifacts={rows.map((item:any)=>({id:item.artifact_id,name:item.delivery.file_name,kind:item.kind,status:item.access?.allowed===true&&['ready','available','ok','payload_available'].includes(item.retrieval?.status)?'ready':'failed'}))} onOpen={id=>void open(id)} labels={{title:'任务成果',empty:'当前任务分段暂无交付文件',open:'查看',ready:'可用',failed:'不可用',processing:'处理中'}} /></>}
    {loading && <p role="status">正在读取成果…</p>}
    {opened && <section className="ze-preview"><header><strong>{opened.delivery?.file_name || opened.label}</strong><button onClick={close} aria-label="关闭成果预览">×</button></header>
      {opened.previewUrl ? <AgentAssetPreview key={`${conversation}:${opened.artifact_id}`} asset={{ artifactId: opened.artifact_id, fileName: opened.delivery?.file_name || '成果', mimeType: opened.delivery?.mime_type || 'application/octet-stream', sizeBytes: opened.delivery?.size_bytes }} resolveArtifact={id => ({ artifactId: id, mimeType: opened.delivery?.mime_type || 'application/octet-stream', url: opened.previewUrl })} maxTextBytes={262144} /> : <p>此文件类型不支持安全预览，请下载查看。</p>}
      <a href={artifactDownloadUrl(conversation, opened.artifact_id,segmentId)} download>下载成果</a>
    </section>}
  </section>;
}
export function Resources({ conversation, catalog, artifacts, api, onError, onNew }: any) {
  const rows=fileArtifacts(artifacts?.artifacts);
  return <details className="ze-resources"><summary>能力与成果资源{rows.length?` · ${rows.length}`:''}</summary><div className="ze-resource-body">
    <ul className="ze-capabilities">{(catalog?.groups || []).map((group: any) => <li key={group.id}><strong>{group.label}</strong><span>{({ partial: '部分可用', available: '可使用', configured: '已配置', needs_configuration: '需配置', unavailable: '不可用', restricted: '当前不可用', not_implemented: '待实现', pending: '待验收' } as any)[group.status] || group.status}</span><p>{group.reason}</p></li>)}</ul>
    {catalog?.legacy_workspace && <p>此历史会话使用旧共享工作区，不能上传私人附件。已升级的新会话可使用独立的私人文件空间。<button onClick={onNew}>新建会话</button></p>}
    {!catalog&&<p>正在读取能力状态…</p>}
    {conversation&&catalog?.runtime_release==='cloud114'&&<><CapabilityControls conversation={conversation} catalog={catalog} api={api} onError={onError}/><KnowledgeControls conversation={conversation} catalog={catalog} api={api} onError={onError}/><ScheduleControls conversation={conversation} catalog={catalog} api={api} onError={onError}/></>}
    {conversation?<HistoricalArtifacts conversation={conversation} catalog={catalog} artifacts={artifacts} api={api} onError={onError}/>:<p>发送消息后可查看任务成果。</p>}
  </div></details>;
}
