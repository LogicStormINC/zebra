// Run in authenticated Chrome. By default this performs ONE read-only model smoke
// in a fresh QA conversation. Returns its ID; after the run, the operator must
// verify native call metadata and remove that Host entry with delete_conversation.
async () => {
  const root=document.querySelector('#zebra-erpnext-root');
  const wait=async fn=>{for(let i=0;i<400;i++){if(fn())return;await new Promise(r=>setTimeout(r,100));}throw Error('Composer check timeout');};
  const check=(v,m)=>{if(!v)throw Error(m);};
  const rpc=async(method,args={})=>{const r=await fetch('/api/method/zebra_erpnext.api.'+method,{method:'POST',headers:{'Content-Type':'application/json','X-Frappe-CSRF-Token':frappe.csrf_token},body:JSON.stringify(args)});const d=await r.json();if(!r.ok||d.exc)throw Error(method+' rejected');return d.message;};
  const change=(el,value)=>{Object.getOwnPropertyDescriptor(el instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLTextAreaElement.prototype,'value').set.call(el,value);el.dispatchEvent(new Event(el instanceof HTMLSelectElement?'change':'input',{bubbles:true}));};
  if(!root.querySelector('.ze-panel'))root.querySelector('.ze-launch').click();
  await wait(()=>root.querySelector('select[aria-label="选择模型"]'));
  const original=frappe.call, captured=[];let fixture;
  try{
    const before=new Set((await rpc('conversations')).map(x=>x.name));
    if(root.querySelector('.ze-create'))root.querySelector('.ze-create').click();
    else [...root.querySelectorAll('.ze-controls button')].find(x=>x.textContent==='新建').click();
    await wait(()=>root.querySelector('select[aria-label="会话"]').value && !before.has(root.querySelector('select[aria-label="会话"]').value));
    fixture=root.querySelector('select[aria-label="会话"]').value;
    frappe.call=function(...args){if(args[0]?.method==='zebra_erpnext.api.submit')captured.push({...args[0].args});return original.apply(this,args);};
    const model=root.querySelector('select[aria-label="选择模型"]'), effort=root.querySelector('select[aria-label="选择思考强度"]');
    check(model.options.length===2 && effort.options.length===4,'Option catalogue mismatch');
    change(model,'deepseek-v4-pro-executor-v1');change(effort,'max');
    await new Promise(r=>setTimeout(r,100));
    const input=root.querySelector('textarea');change(input,'这是输入框配置验收。只回复“配置验收通过”，不要查询或修改业务，不要调用工具。');
    await new Promise(r=>setTimeout(r,100));
    const shift=new KeyboardEvent('keydown',{key:'Enter',shiftKey:true,bubbles:true,cancelable:true});input.dispatchEvent(shift);
    const ime=new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true});input.dispatchEvent(ime);
    await new Promise(r=>setTimeout(r,100));check(captured.length===0&&!shift.defaultPrevented&&!ime.defaultPrevented,'IME or Shift+Enter submitted');
    root.querySelector('[aria-label="发送"]').click();
    await wait(()=>captured.length===1);
    check(captured[0].model_profile==='deepseek-v4-pro-executor-v1'&&captured[0].reasoning_effort==='max','Selection not in submit');
    return {fixture,model:'deepseek-v4-pro-executor-v1',reasoning:'max',options:[...model.options].map(x=>x.text),efforts:[...effort.options].map(x=>x.text),shiftEnterAndIME:true,submitted:true};
  }finally{frappe.call=original;}
}
