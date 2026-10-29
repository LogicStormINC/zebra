import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AgentContentRenderer } from '@zebra-agent/react';
import { AgentVegaLiteRenderer } from '@zebra-agent/react-charts';
import { toBlob } from 'html-to-image';
import { artifactPreviewUrl, normalizeParts, reportDownloadUrl, safeSources, visibleContent, answerBody } from './protocol.mjs';
import { FileCard, downloadBlob } from './resources';

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) { try { await navigator.clipboard.writeText(text); return; } catch {} }
  const focused = document.activeElement, node = document.createElement('textarea');
  node.value = text; node.style.position = 'fixed'; node.style.opacity = '0'; document.body.appendChild(node); node.select();
  try { if (!document.execCommand('copy')) throw new Error('复制失败，请手动选择正文复制。'); }
  finally { node.remove(); if (focused instanceof HTMLElement) focused.focus({ preventScroll: true }); }
}
export function Markdown({ content }: { content: string }) {
  // ponytail: Frappe already sanitizes Markdown; keep one parser for ERP content.
  return typeof window.frappe.markdown === 'function' ? <div className="ze-markdown" dangerouslySetInnerHTML={{ __html: window.frappe.markdown(visibleContent(content)) }} /> : <div className="ze-markdown">{visibleContent(content)}</div>;
}
function RichFile({ part, context }: any) {
  return <FileCard conversation={context.conversation} artifact={{artifact_id:part.artifactId,kind:'file',access:{allowed:true},retrieval:{status:part.state==='ready'?'available':part.state},delivery:{file_name:part.fileName||part.name,mime_type:part.mimeType,size_bytes:part.sizeBytes}}} onOpen={() => context.onPreview(part.artifactId)} />;
}
export function Answer({ message, conversation, api, busy, latest, actions, onPick, onRegenerate, onChanged, onPreview }: any) {
  const [working, setWorking] = useState(''), [notice, setNotice] = useState(''), [error, setError] = useState(''), [retry, setRetry] = useState(false);
  const alive = useRef(true), gate = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const content = answerBody(message), parts = useMemo(() => normalizeParts(message.parts), [message.parts]), sources = safeSources(message.sources);
  const renderFile = useCallback((props:any) => <RichFile {...props} context={{...props.context,conversation,onPreview}} />, [conversation,onPreview]);
  const renderers = useMemo(() => ({chart:AgentVegaLiteRenderer,file:renderFile}), [renderFile]);
  const resolveArtifact = useCallback((id: string) => {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(id)) throw new Error('资源标识无效');
    const part = parts.find((item:any)=>item.artifactId===id);
    return { artifactId:id, mimeType:part?.mimeType || 'application/json', url:artifactPreviewUrl(conversation,id) };
  }, [parts,conversation]);
  async function act(key: string, action: () => Promise<any>, success: string) {
    if (gate.current) return;
    gate.current = true; setWorking(key); setError(''); setNotice('');
    try { const result = await action(); if (alive.current) { if (result?.digest) onChanged(result); setNotice(success); if (key==='retry') setRetry(false); } }
    catch (error) { if (alive.current) setError(error instanceof Error ? error.message : '操作结果未确认，请重新连接核对后重试。'); }
    finally { gate.current = false; if (alive.current) setWorking(''); }
  }
  async function exportImage() {
    const host = document.createElement('section');
    host.className = 'ze-share-card'; host.setAttribute('aria-hidden','true');
    Object.assign(host.style, {position:'fixed',left:'-10000px',top:'0',width:'960px',padding:'48px',background:'#fff',color:'#20252d',font:'16px/1.75 system-ui'});
    const title = document.createElement('h2'); title.textContent = 'zebra · ERP 工作摘要'; host.appendChild(title);
    const text = document.createElement('div'); text.className = 'ze-markdown';
    if (typeof window.frappe.markdown === 'function') text.innerHTML = window.frappe.markdown(content);
    else text.textContent = content;
    host.appendChild(text);
    // Normalize the same text used by copy/report; independent Parts never enter
    // this export tree. Inline Markdown images also remain outside body export.
    host.querySelectorAll('img,video,iframe').forEach(node => node.remove());
    document.getElementById('zebra-erpnext-root')!.appendChild(host);
    try {
      if (host.scrollHeight > 16000) throw new Error('正文较长，请下载 Markdown 保存完整内容。');
      const blob = await toBlob(host, {width:960,height:host.scrollHeight,pixelRatio:1,skipFonts:true,cacheBust:false,style:{position:'static',left:'auto',top:'auto',transform:'none'}});
      if (!blob) throw new Error('图片导出失败，请重试或下载正文。');
      downloadBlob(blob, 'zebra-answer.png');
    } finally { host.remove(); }
  }
  if (message.role !== 'assistant') return <><span>{message.content}</span>{message.attachments?.length>0 && <div className="ze-message-attachments" aria-label="本条消息附件">{message.attachments.map((file:any) => <span key={file.attachment_id || file.file_name}>▤ {file.file_name} · {Number.isSafeInteger(file.original_size_bytes || file.size_bytes) ? `${file.original_size_bytes || file.size_bytes} B` : '大小未知'}<small>已提交附件 · 原文件下载尚未开放</small></span>)}</div>}</>;
  const verified = !!message.digest && !message.content_truncated;
  const coordinates = {conversation,message_id:message.id,digest:message.digest};
  return <section className="ze-answer">
    <div>{!parts.some((part:any)=>part.type==='text') && <Markdown content={content} />}
    {parts.length>0 && <AgentContentRenderer message={{...message,content:'',parts}} renderText={part => part.format==='markdown'?<Markdown content={part.text} />:<span>{visibleContent(part.text)}</span>} renderers={renderers} resolveArtifact={resolveArtifact} labels={{openExternalVideo:'打开原视频',playExternalVideo:'播放视频'}} />}</div>
    {sources.length>0 && <details className="ze-sources"><summary>来源 · {sources.length}</summary>{sources.map((source:any) => <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>)}</details>}
    {message.digest && message.status!=='streaming' && <section className="ze-answer-actions" aria-label="回答操作">
      {latest && !busy && actions.length>0 && <div className="ze-quick-actions">{actions.map((action:any) => <button key={action.id} onClick={()=>onPick(action.prompt)}>✧ {action.label}</button>)}</div>}
      <div className="ze-action-row" role="group" aria-label="复制与导出">
        <button disabled={!!working||!content.trim()} onClick={()=>void act('copy',()=>copyText(content),'已复制正文')}>复制正文</button>
        <button disabled={!content.trim()} onClick={()=>downloadBlob(new Blob([content],{type:'text/markdown;charset=utf-8'}),'zebra-answer.md')}>下载正文</button>

      </div>
      <details className="ze-more-actions"><summary>••• 更多操作</summary><div className="ze-action-row">
                <button disabled={!!working||!content.trim()} title="导出回答正文，不包含独立图表、视频或附件" onClick={()=>void act('image',exportImage,'已发起正文图片下载（不含独立图表、视频或附件）')}>{working==='image'?'生成中…':'导出图片'}</button>
        {verified && (message.report_saved ? <a href={reportDownloadUrl(conversation,message)} download>查看已保存报告</a> : <button disabled={!!working||busy} onClick={()=>void act('report',()=>api('save_report',coordinates),'私人报告已保存')}>{working==='report'?'保存中…':'保存报告'}</button>)}
        <span>评价回答</span>{[['helpful','有帮助'],['unhelpful','需改进']].map(([value,label])=><button key={value} disabled={!!working||busy||!verified} aria-pressed={message.feedback===value} onClick={()=>void act('feedback',()=>api('answer_feedback',{...coordinates,feedback:value}),'反馈已保存')}>{label}</button>)}
        <button disabled={!!working} onClick={()=>void act('cite',()=>copyText(`【zebra ERP 引用】\n${content.replace(/[#>*_`]/g,'').slice(0,360)}\n${sources.map((source:any)=>`${source.title} ${source.url}`).join('\n')}\n会话：${conversation} · 回答：${message.id}\n请结合原始单据与来源核对。`),'已复制引用摘要')}>复制引用摘要</button>
        {latest && verified && !busy && <button aria-expanded={retry} onClick={()=>setRetry(!retry)}>重新处理</button>}
      </div>{retry && latest && !busy && <div className="ze-retry-confirm"><p>重新提交上一条文字请求（不重传附件），将新增一轮处理，保留原回答。未发送的草稿与附件会保留。</p><button disabled={!!working} onClick={()=>void act('retry',onRegenerate,'已提交重新处理请求')}>确认重新处理</button><button disabled={!!working} onClick={()=>setRetry(false)}>取消</button></div>}</details>
      {!verified && <small>重新连接核对完整公开回答后，可保存报告或反馈。</small>}
      {notice && <p role="status">{notice}</p>}{error && <p className="ze-action-error" role="alert">{error}</p>}
    </section>}
  </section>;
}
