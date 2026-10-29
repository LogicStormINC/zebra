import React, {useState, useRef, useEffect} from 'react';
import {ResourceFiles} from './resources';

/** File storage browser: current conversation's delivered files across task segments. */
export function HistoricalArtifacts({conversation,catalog,artifacts,api,onError}:any) {
  const [segments,setSegments]=useState<any[]>([]),[selected,setSelected]=useState(''),[page,setPage]=useState<any>(null),[after,setAfter]=useState(-1),[stack,setStack]=useState<number[]>([]),[rows,setRows]=useState<any>(artifacts),[busy,setBusy]=useState(false);
  const gate=useRef(false),generation=useRef(0);
  const cloud=catalog?.runtime_release==='cloud114';
  async function loadPage(cursor=-1,previous=false) {
    if(gate.current)return;gate.current=true;setBusy(true);
    try {const value=await api('artifact_segments',{conversation,after:cursor});setSegments(value.segments||[]);setPage(value);setAfter(cursor);setStack(previous?stack.slice(0,-1):cursor===-1?[]:[...stack,after]);}
    catch(e){onError(e);} finally{gate.current=false;setBusy(false);}
  }
  async function choose(id:string) {
    const revision=++generation.current;setSelected(id);setBusy(true);
    try {const value=id?await api('task_artifacts',{conversation,segment_id:id}):artifacts;if(revision===generation.current)setRows(value);}
    catch(e){if(revision===generation.current)onError(e);} finally{if(revision===generation.current)setBusy(false);}
  }
  useEffect(()=>{if(cloud)void loadPage();},[conversation]);
  return <section className="ze-set" aria-label="文件存储">
    <div className="ze-set-block">
      <div className="ze-set-block-head"><h4>文件存储</h4><p>本会话产出的文件与任务成果；跨分段可追溯、逐次授权下载。</p>
        {cloud&&<div className="ze-set-block-actions"><button className="ze-btn" disabled={busy} onClick={()=>void loadPage()}>刷新分段</button></div>}
      </div>
      {cloud&&<div className="ze-set-inline">
        <label className="ze-set-inline-label">成果范围<select className="ze-set-select" value={selected} disabled={busy} onChange={e=>void choose(e.target.value)}><option value="">当前分段</option>{segments.map(row=><option key={row.segment_id} value={row.segment_id}>分段 {row.segment_index+1}</option>)}</select></label>
        <div className="ze-set-inline ze-set-inline--gap">
          <button className="ze-btn" disabled={busy||!stack.length} onClick={()=>void loadPage(stack[stack.length-1],true)}>上一页</button>
          <button className="ze-btn" disabled={busy||!page?.has_more} onClick={()=>void loadPage(page.next_after)}>下一页</button>
        </div>
      </div>}
      {busy?<p className="ze-set-empty" role="status">正在读取文件…</p>
        :<ResourceFiles key={`${conversation}:${selected}`} conversation={conversation} segmentId={selected} artifacts={selected?rows:artifacts} api={api} onError={onError}/>}
    </div>
  </section>;
}
