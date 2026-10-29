import React,{useState,useRef,useEffect} from 'react';

const statusName:any={active:'已启用',paused:'已暂停',creating:'创建待确认',pausing:'暂停待确认',resuming:'启用待确认'};

export function ScheduleControls({conversation,catalog,api,onError}:any) {
  const [rows,setRows]=useState<any[]>([]),[title,setTitle]=useState(''),[prompt,setPrompt]=useState(''),[kind,setKind]=useState('daily'),[time,setTime]=useState('09:00'),[once,setOnce]=useState(''),[detail,setDetail]=useState<any>(null),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
  const gate=useRef(false),pending=useRef<any>(null);
  const enabled=catalog.groups?.find((g:any)=>g.id==='schedules')?.status==='available';
  async function run(work:()=>Promise<any>) {if(gate.current)return;gate.current=true;setBusy(true);setNotice('');try{await work();}catch(e){onError(e);}finally{gate.current=false;setBusy(false);}}
  async function load(){const result=await api('schedule_inventory',{conversation});setRows(result.schedules||[]);}
  async function create(){const trigger=kind==='daily'?{kind,local_time:time+':00'}:{kind,fire_at:new Date(once).toISOString()};const body={conversation,title,prompt,trigger:JSON.stringify(trigger),timezone:'Asia/Shanghai'};const intent=JSON.stringify(body);if(!pending.current||pending.current.intent!==intent)pending.current={intent,body:{...body,request_id:crypto.randomUUID()}};await api('schedule_create',pending.current.body);pending.current=null;setTitle('');setPrompt('');setNotice('计划已保存。每次执行都会重新检查权限。');await load();}
  async function action(operation:string){await api('schedule_action',{conversation,name:detail.name,operation,schedule_version:detail.schedule_version});setDetail(null);await load();}
  useEffect(()=>{if(enabled)void run(load);},[conversation]);
  if(!enabled)return <p className="ze-set-note">此会话当前运行时尚未开放定时任务。</p>;
  return <section className="ze-set">
    <div className="ze-set-block">
      <div className="ze-set-block-head"><h4>定时任务（{rows.length}）</h4><p>原生持久调度；每次执行重新检查权限，不会自动批准业务写入。</p>
        <div className="ze-set-block-actions"><button className="ze-btn" disabled={busy} onClick={()=>void run(load)}>刷新</button></div>
      </div>
      {rows.length?<ul className="ze-set-rows">{rows.map(row=><li key={row.name} className="ze-set-row">
        <span className="ze-set-row-title">{row.title}</span>
        <span className={`ze-badge ${row.status==='active'?'ze-badge--ok':'ze-badge--neutral'}`}>{statusName[row.status]||row.status}</span>
        <button className="ze-btn" disabled={busy} onClick={()=>void run(async()=>setDetail(await api('schedule_detail',{conversation,name:row.name})))}>详情</button>
      </li>)}</ul>:<p className="ze-set-empty">还没有定时任务；在下方创建。</p>}
      {detail&&<div className="ze-set-form ze-set-form--card" aria-label="计划详情">
        <div className="ze-set-inline"><strong>{detail.title}</strong><span className={`ze-badge ${detail.status==='active'?'ze-badge--ok':'ze-badge--neutral'}`}>{statusName[detail.status]||detail.status}</span></div>
        {detail.pending?<p className="ze-set-note">创建结果尚未确认；请用原请求核对，不会生成重复计划。</p>
        :<><p className="ze-set-meta">下次执行：{detail.next_fire_at||'无'}</p><p>{detail.task_template?.prompt}</p></>}
        <div className="ze-set-inline ze-set-inline--gap">
          {!detail.pending&&<button className="ze-btn" disabled={busy} onClick={()=>void run(()=>action(detail.status==='active'?'pause':'resume'))}>{detail.status==='active'?'暂停':'启用'}</button>}
          {!detail.pending&&<button className="ze-btn ze-btn--danger" disabled={busy} onClick={()=>void run(()=>action('delete'))}>删除计划</button>}
          <button className="ze-btn" disabled={busy} onClick={()=>setDetail(null)}>关闭</button>
        </div>
      </div>}
    </div>
    <div className="ze-set-block">
      <div className="ze-set-block-head"><h4>新建定时任务</h4><p>时区 Asia/Shanghai；继承当前会话的模型、思考强度与能力选择。</p></div>
      <form className="ze-set-form" onSubmit={e=>{e.preventDefault();void run(create);}}>
        <label>计划名称<input required maxLength={120} value={title} disabled={busy} onChange={e=>setTitle(e.target.value)} placeholder="例如：每天早晨的库存预警"/></label>
        <label>执行内容<textarea required maxLength={30000} rows={3} value={prompt} disabled={busy} onChange={e=>setPrompt(e.target.value)} placeholder="描述要让 zebra 定时执行的任务…"/></label>
        <div className="ze-set-grid">
          <label>执行时间<select className="ze-set-select" value={kind} disabled={busy} onChange={e=>setKind(e.target.value)}><option value="daily">每天</option><option value="once">仅一次</option></select></label>
          {kind==='daily'?<label>时刻<input type="time" required value={time} disabled={busy} onChange={e=>setTime(e.target.value)}/></label>:<label>日期时间<input type="datetime-local" required value={once} disabled={busy} onChange={e=>setOnce(e.target.value)}/></label>}
        </div>
        <button className="ze-btn-primary" disabled={busy||!title.trim()||!prompt.trim()} type="submit">保存定时任务</button>
      </form>
    </div>
    {notice&&<p className="ze-set-ok" role="status">{notice}</p>}
  </section>;
}
