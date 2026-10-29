import React,{useState,useRef,useEffect} from 'react';
import {attachmentInfo} from './protocol.mjs';
import {BookIcon, PlusIcon} from './components/icons';

export function KnowledgeControls({conversation,catalog,api,onError}:any) {
  const [sources,setSources]=useState<any[]>([]),[selected,setSelected]=useState<string[]>([]),[memories,setMemories]=useState<any[]>([]),[text,setText]=useState(''),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
  const gate=useRef(false),fileInput=useRef<HTMLInputElement>(null);
  const enabled=catalog.groups?.find((g:any)=>g.id==='knowledge')?.status==='available';
  async function run(work:()=>Promise<any>) {if(gate.current)return;gate.current=true;setBusy(true);setNotice('');try{await work();}catch(e){onError(e);}finally{gate.current=false;setBusy(false);}}
  async function load() {const [a,b]=await Promise.all([api('knowledge_inventory',{conversation}),api('memory_manage',{conversation})]);setSources(a.sources||[]);setSelected(a.selected||[]);setMemories(b.memories||[]);}
  async function upload(file:File) {
    const info=attachmentInfo(file,'deepseek-v4-flash-executor-v1');if(!info||file.size>16777216)throw Error('资料类型不支持或超过 16 MiB 上限');
    const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
    await api('knowledge_create',{conversation,title:file.name.slice(0,120),attachment:JSON.stringify({file_name:file.name,media_type:info.mime,content_base64:btoa(binary)})});await load();
  }
  useEffect(()=>{if(enabled)void run(load);},[conversation]);
  if(!enabled)return <p className="ze-set-note">此会话当前运行时尚未开放知识资料与记忆。</p>;
  return <section className="ze-set">
    <div className="ze-set-block">
      <div className="ze-set-block-head"><h4>知识资料</h4><p>只对当前用户与公司开放；选择后随下一条消息发送，与普通附件共用预算。</p>
        <div className="ze-set-block-actions"><input ref={fileInput} type="file" hidden onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void run(()=>upload(file));}}/><button className="ze-btn" disabled={busy} onClick={()=>fileInput.current?.click()}><PlusIcon size={12}/>上传资料</button></div>
      </div>
      {sources.length?<ul className="ze-set-rows">{sources.map(row=><li key={row.name} className="ze-set-row">
        <label className="ze-set-check"><input type="checkbox" checked={selected.includes(row.name)} disabled={busy||(!selected.includes(row.name)&&selected.length>=4)} onChange={e=>setSelected(old=>e.target.checked?[...old,row.name]:old.filter(id=>id!==row.name))}/><span className="ze-set-row-title">{row.title}</span></label>
        <button className="ze-btn ze-btn--danger" disabled={busy} onClick={()=>void run(async()=>{await api('knowledge_remove',{conversation,name:row.name});await load();})}>删除</button>
      </li>)}</ul>
      :<p className="ze-set-empty">还没有知识资料；上传后可选择随消息发送。</p>}
      <div className="ze-set-inline"><span className="ze-set-meta">已选 {selected.length}/4</span><button className="ze-btn-primary" disabled={busy} onClick={()=>void run(async()=>{await api('knowledge_select',{conversation,source_ids:JSON.stringify(selected)});setNotice('资料选择已保存。');})}>保存资料选择</button></div>
    </div>
    <div className="ze-set-block">
      <div className="ze-set-block-head"><h4>工作区记忆</h4><p><BookIcon size={12}/> zebra 在此会话沉淀的长期记忆；可修改或删除。</p></div>
      {memories.length?<ul className="ze-set-cards">{memories.map(row=><li key={row.memory_id} className="ze-set-card">
        <p>{row.text}</p>
        <div className="ze-set-card-foot"><span className={`ze-badge ${row.status==='confirmed'?'ze-badge--ok':'ze-badge--neutral'}`}>{row.status==='confirmed'?'已确认':row.status}</span>
          {row.status==='confirmed'&&<div className="ze-set-row-actions"><button className="ze-btn" disabled={busy} onClick={()=>{const next=window.prompt('修改记忆',row.text);if(next?.trim())void run(async()=>{await api('memory_manage',{conversation,action:'replace',memory_id:row.memory_id,text:next});await load();});}}>修改</button><button className="ze-btn ze-btn--danger" disabled={busy} onClick={()=>void run(async()=>{await api('memory_manage',{conversation,action:'delete',memory_id:row.memory_id});await load();})}>删除</button></div>}
        </div>
      </li>)}</ul>:<p className="ze-set-empty">此工作区还没有记忆。</p>}
      <div className="ze-set-form ze-set-form--card"><label>明确保存一条记忆<textarea value={text} disabled={busy} maxLength={4000} rows={3} onChange={e=>setText(e.target.value)}/></label><button className="ze-btn-primary" disabled={busy||!text.trim()} onClick={()=>void run(async()=>{await api('memory_manage',{conversation,action:'create',text});setText('');await load();})}>保存记忆</button></div>
    </div>
    {notice&&<p className="ze-set-ok" role="status">{notice}</p>}
  </section>;
}
