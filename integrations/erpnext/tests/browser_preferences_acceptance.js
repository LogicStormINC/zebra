// Run once with stage='create', reload, stage='restoreB', reload, stage='restoreA'.
// Uses empty QA conversations: no models or business writes. Final stage removes both.
async (stage = 'create') => {
  const root=document.querySelector('#zebra-erpnext-root');
  const check=(v,m)=>{if(!v)throw Error(m);};
  const wait=async fn=>{for(let i=0;i<120;i++){if(fn())return;await new Promise(r=>setTimeout(r,50));}throw Error('Preferences UI timeout');};
  const rpc=async(method,args={})=>{const r=await fetch('/api/method/zebra_erpnext.api.'+method,{method:'POST',headers:{'Content-Type':'application/json','X-Frappe-CSRF-Token':frappe.csrf_token},body:JSON.stringify(args)});const d=await r.json();if(!r.ok||d.exc)throw Error(method+' rejected');return d.message;};
  const el=label=>root.querySelector('select[aria-label="'+label+'"]');
  const change=(node,value)=>{Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(node,value);node.dispatchEvent(new Event('change',{bubbles:true}));};
  const ready=()=>root.querySelector('.ze-composer-fieldset')&&!root.querySelector('.ze-composer-fieldset').disabled;
  const assertValues=(model,effort)=>check(el('选择模型').value===model&&el('选择思考强度').value===effort,'Conversation preferences mixed or reset');
  if(!root.querySelector('.ze-panel'))root.querySelector('.ze-launch').click();
  await wait(()=>el('选择模型')&&ready());
  if(stage==='create'){
    const create=async()=>{const previous=el('会话').value;if(root.querySelector('.ze-create'))root.querySelector('.ze-create').click();else [...root.querySelectorAll('.ze-controls button')].find(x=>x.textContent==='新建').click();await wait(()=>el('会话').value&&el('会话').value!==previous&&ready());return el('会话').value;};
    const save=async(label,value)=>{change(el(label),value);await new Promise(r=>setTimeout(r,50));await wait(ready);};
    const a=await create();await save('选择模型','deepseek-v4-pro-executor-v1');await save('选择思考强度','low');
    const b=await create();assertValues('deepseek-v4-flash-executor-v1','high');await save('选择思考强度','max');
    const one=await rpc('conversation_settings',{conversation:a}),two=await rpc('conversation_settings',{conversation:b});
    check(one.model_profile==='deepseek-v4-pro-executor-v1'&&one.reasoning_effort==='low','A not saved');check(two.model_profile==='deepseek-v4-flash-executor-v1'&&two.reasoning_effort==='max','B not saved');
    sessionStorage.setItem('zebra-test:prefs',JSON.stringify({a,b}));return {stage,a,b,savedBeforeSending:true,newConversationDefaults:true};
  }
  const {a,b}=JSON.parse(sessionStorage.getItem('zebra-test:prefs'));
  await wait(()=>el('会话').value===(stage==='restoreB'?b:a)&&ready());
  if(stage==='restoreB'){
    assertValues('deepseek-v4-flash-executor-v1','max');change(el('会话'),a);await wait(()=>el('会话').value===a&&ready());assertValues('deepseek-v4-pro-executor-v1','low');
    change(el('会话'),b);await wait(()=>el('会话').value===b&&ready());assertValues('deepseek-v4-flash-executor-v1','max');
    change(el('会话'),a);await wait(()=>el('会话').value===a&&ready());assertValues('deepseek-v4-pro-executor-v1','low');
    return {stage,refreshRestoredB:true,switchingIsolated:true};
  }
  assertValues('deepseek-v4-pro-executor-v1','low');
  await rpc('delete_conversation',{conversation:a});await rpc('delete_conversation',{conversation:b});sessionStorage.removeItem('zebra-test:prefs');
  return {stage,refreshRestoredA:true,fixturesRemoved:true};
}
