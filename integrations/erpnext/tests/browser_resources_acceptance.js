// Run in the authenticated browser after loading the current bundle. All changed
// Host replies and SSE are mocked in this tab: no model call, upload or business write.
async ({ requireReducedMotion = false, requireMobile = false } = {}) => {
  const root = document.querySelector('#zebra-erpnext-root');
  const wait = async fn => { await new Promise(r=>setTimeout(r,25)); for (let i=0;i<160;i++) { if (fn()) return; await new Promise(r=>setTimeout(r,25)); } throw Error('Resource UI timeout'); };
  const check = (value, reason) => { if (!value) throw Error(reason); };
  if (!root.querySelector('.ze-panel')) root.querySelector('.ze-launch').click();
  await wait(()=>root.querySelector('.ze-controls'));
  const originalRoute = frappe.get_route;
  const call = frappe.call, fetchOriginal = window.fetch, captured = [], before = root.querySelector('select[aria-label="会话"]')?.value;
  const fixtures = [{name:'qa-ui-private-a',title:'Resource QA A',company:frappe.defaults.get_user_default('Company')},{name:'qa-ui-private-b',title:'Resource QA B',company:frappe.defaults.get_user_default('Company')}];
  let created = 0, rejectSubmit = false;
  let snapshotState = { status:'awaiting_turn', run_state:{phase:'idle',availableActions:[]}, clarification:null };
  const originalRead = File.prototype.arrayBuffer, createUrl = URL.createObjectURL, revokeUrl = URL.revokeObjectURL, liveUrls = new Set();
  URL.createObjectURL = function(blob) { const value=createUrl.call(this,blob);liveUrls.add(value);return value; };
  URL.revokeObjectURL = function(value) { liveUrls.delete(value);return revokeUrl.call(this,value); };
  const settings = { model_profile:'deepseek-v4-flash-executor-v1', reasoning_effort:'high', company:fixtures[0].company };
  const change = (element,value) => { Object.getOwnPropertyDescriptor(element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLTextAreaElement.prototype,'value').set.call(element,value); element.dispatchEvent(new Event(element instanceof HTMLSelectElement?'change':'input',{bubbles:true})); };
  const choose = files => { const transfer = new DataTransfer(); files.forEach(file=>transfer.items.add(file)); const input=root.querySelector('input[type="file"]'); input.files=transfer.files; input.dispatchEvent(new Event('change',{bubbles:true})); };
  try {
    frappe.call = function(options, ...rest) {
      const method=options?.method?.replace('zebra_erpnext.api.','');
      let message;
      if (method === 'create_conversation') message=fixtures[created++ % fixtures.length];
      else if (method === 'conversations') message=fixtures;
      else if (method === 'conversation_settings') message=settings;
      else if (method === 'save_conversation_settings') message=Object.assign(settings,options.args);
      else if (method === 'snapshot') message={...snapshotState,messages:[{id:'qa-u',role:'user',content:'fixture'},{id:'qa-a',role:'assistant',content:'资源测试回复'}],client_surface:null};
      else if (method === 'approvals') message=[];
      else if (method === 'capability_catalog') message={private_uploads:true,legacy_workspace:false,groups:[{id:'files',label:'文件与图片',status:'available',reason:'测试隔离工作区'}]};
      else if (method === 'task_usage') message={model_usage:{input_tokens:100,input_token_limit:1000,cache_hit_tokens:2,cache_miss_tokens:8}};
      else if (method === 'task_artifacts') message={artifacts:[{artifact_id:'owned-id',kind:'file',label:'Owned text',retrieval:{status:'available'},access:{allowed:true},delivery:{file_name:'owned.txt',mime_type:'text/plain',size_bytes:2}}],history_scope:'active_segment'};
      else if (method === 'artifact_detail') message={artifact:{artifact_id:'owned-id',delivery:{file_name:'owned.txt',mime_type:'text/plain',size_bytes:2}}};
      else if (method === 'artifact_content') message={artifact_id:'owned-id',status:'ok',encoding:'base64',content_base64:'b2s=',size_bytes:2,media_type:'text/plain'};
      else if (method === 'submit') { captured.push({...options.args}); if (rejectSubmit) { queueMicrotask(()=>options.error({})); return Promise.resolve(); } message={client_surface:null}; }
      else return call.call(this,options,...rest);
      queueMicrotask(()=>options.callback({message})); return Promise.resolve({message});
    };
    window.fetch = async (...args) => String(args[0]).startsWith('/api/method/zebra_erpnext.api.events?')
      ? new Response('data: {"type":"RUN_FINISHED"}\n\n',{headers:{'Content-Type':'text/event-stream'}}) : fetchOriginal(...args);
    const newConversation=()=>{const button=root.querySelector('.ze-create') || [...root.querySelectorAll('.ze-controls button')].find(button=>button.textContent==='新建');button.click();};
    newConversation(); await wait(()=>root.querySelector('select[aria-label="会话"]')?.value===fixtures[0].name && !root.querySelector('fieldset').disabled);
    const transfer = new DataTransfer();transfer.items.add(new File(['hello'],'qa.txt',{type:'text/plain'}));
    root.querySelector('fieldset').dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));
    await wait(()=>root.querySelector('[aria-label="移除附件：qa.txt"]') && !root.querySelector('fieldset').disabled);
    check(root.querySelector('textarea').value.includes('附件'),'Attachment-only editable prompt missing');
    root.querySelector('.ze-attachment-previews button').click();await wait(()=>root.querySelector('.zebra-agent-asset-preview'));
    root.querySelector('[aria-label="移除附件：qa.txt"]').click(); await wait(()=>!root.querySelector('.ze-attachment-previews'));
    choose([new File(['x'],'bad.svg',{type:'image/svg+xml'})]);await wait(()=>root.querySelector('[role="alert"]')?.textContent.includes('不支持'));check(!root.querySelector('.ze-attachment-previews'),'Invalid file retained');
    choose([new File(['hello'],'qa.txt',{type:'text/plain'})]);await wait(()=>root.querySelector('[aria-label="移除附件：qa.txt"]')&&!root.querySelector('fieldset').disabled);
    rejectSubmit=true;root.querySelector('[aria-label="发送"]').click();await wait(()=>captured.length===1&&!root.querySelector('[aria-label="发送"]').disabled);
    change(root.querySelector('select[aria-label="选择思考强度"]'),'max');await new Promise(resolve=>setTimeout(resolve,50));
    frappe.get_route=()=>['Form','Customer','qa-context-changed'];
    root.querySelector('[aria-label="发送"]').click();await wait(()=>captured.length===2&&!root.querySelector('[aria-label="发送"]').disabled);
    check(captured[0].request_id===captured[1].request_id && captured[0].attachments===captured[1].attachments && captured[0].reasoning_effort===captured[1].reasoning_effort,'Retry changed immutable request coordinates');
    check(captured[0].context===captured[1].context,'Retry changed the original page context after navigation');frappe.get_route=originalRoute;
    const wire=JSON.parse(captured[0].attachments)[0];check(Object.keys(wire).sort().join(',')==='content_base64,file_name,media_type'&&atob(wire.content_base64)==='hello','Invalid wire payload');
    rejectSubmit=false;root.querySelector('[aria-label="发送"]').click();await wait(()=>captured.length===3&&!root.querySelector('[aria-label="停止"]'));
    check(!root.querySelector('.ze-attachment-previews'),'Successful send retained attachments');
    choose([new File(['later'],'followup.txt',{type:'text/plain'})]);await wait(()=>root.querySelector('[aria-label="移除附件：followup.txt"]')&&!root.querySelector('fieldset').disabled);
    root.querySelector('[aria-label="发送"]').click();await wait(()=>captured.length===4&&!root.querySelector('[aria-label="停止"]'));
    check(JSON.parse(captured[3].attachments)[0].file_name==='followup.txt','Follow-up dropped files');
    await wait(()=>root.querySelector('.ze-inline-files [aria-label="预览 owned.txt"]'));
    root.querySelector('.ze-inline-files [aria-label="预览 owned.txt"]').click();await wait(()=>root.querySelector('.ze-inline-files .ze-preview a'));
    const href=new URL(root.querySelector('.ze-inline-files .ze-preview a').href);check(href.origin===location.origin&&href.pathname==='/api/method/zebra_erpnext.api.artifact_download'&&href.searchParams.get('artifact_id')==='owned-id','Untrusted download URL');
    change(root.querySelector('select[aria-label="选择模型"]'),'deepseek-v4-pro-executor-v1');await new Promise(resolve=>setTimeout(resolve,50));
    choose([new File([Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j90cAAAAASUVORK5CYII='),c=>c.charCodeAt(0))],'photo.png',{type:'image/png'})]);
    await wait(()=>root.querySelector('[role="alert"]')?.textContent.includes('Pro'));check(!root.querySelector('[aria-label="移除附件：photo.png"]'),'Pro image silently accepted');
    change(root.querySelector('select[aria-label="选择模型"]'),'deepseek-v4-flash-executor-v1');await new Promise(resolve=>setTimeout(resolve,50));
    choose([new File(['private'],'private.txt',{type:'text/plain'})]);await wait(()=>root.querySelector('[aria-label="移除附件：private.txt"]')&&!root.querySelector('fieldset').disabled);
    newConversation();await wait(()=>root.querySelector('select[aria-label="会话"]')?.value===fixtures[1].name);
    check(!root.querySelector('.ze-attachment-previews')&&!root.querySelector('textarea').value&&!root.querySelector('.ze-preview'),'Conversation switch leaked private draft/preview');
    let finishRead;File.prototype.arrayBuffer=function(){if(this.name==='delayed.txt')return new Promise(resolve=>{finishRead=()=>resolve(new TextEncoder().encode('delayed').buffer);});return originalRead.call(this);};
    choose([new File(['delayed'],'delayed.txt',{type:'text/plain'})]);await wait(()=>finishRead);
    newConversation();await wait(()=>root.querySelector('select[aria-label="会话"]')?.value===fixtures[0].name);
    check(liveUrls.size===0,'Switch retained object URL while file read remained unresolved');
    finishRead();await new Promise(resolve=>setTimeout(resolve,50));
    check(!root.querySelector('[aria-label="移除附件：delayed.txt"]')&&liveUrls.size===0,'Delayed file read leaked into another conversation or retained object URL');
    const reduced=matchMedia('(prefers-reduced-motion:reduce)').matches;
    if(requireReducedMotion)check(reduced&&getComputedStyle(root.querySelector('.zebra-agent-composer__action')).transitionDuration==='0s','Reduced-motion setting/CSS missing');
    if(requireMobile)check(innerWidth<=700&&root.querySelector('.ze-panel').getBoundingClientRect().width<=innerWidth,'Mobile overflow');
    const reconnect=[...root.querySelectorAll('.ze-context button')].find(button=>button.textContent==='重新连接');reconnect.click();await wait(()=>root.textContent.includes('资源测试回复'));
    check(!root.querySelector('.ze-attachment-previews'),'Durable snapshot recovery restored private draft');
    snapshotState={status:'waiting_input',run_state:{phase:'waiting_for_user',availableActions:[]},clarification:{clarification_id:'qa-active',question:'请选择测试仓库',choices:[]}};
    reconnect.click();await wait(()=>root.textContent.includes('请选择测试仓库'));
    check(root.querySelector('.zebra-agent-run-status')?.textContent.includes('等待补充信息'),'Flat snapshot lost waiting state');
    snapshotState={status:'queued',run_state:{phase:'queued',queuePosition:3,availableActions:[]},clarification:null};
    reconnect.click();await wait(()=>root.querySelector('.zebra-agent-run-status')?.textContent.includes('排队中 · 3'));
    snapshotState={status:'ready',run_state:{phase:'reconciling',safeMessage:'测试提交结果正在核对',availableActions:[]},clarification:null};
    reconnect.click();await wait(()=>root.querySelector('.zebra-agent-run-status')?.textContent.includes('测试提交结果正在核对'));
    check(!root.textContent.includes('请选择测试仓库'),'Old clarification survived a new snapshot');
    snapshotState={status:'awaiting_turn',run_state:{phase:'idle',availableActions:[]},clarification:null};
    reconnect.click();await wait(()=>root.querySelector('.zebra-agent-run-status')?.textContent.includes('等待消息')&&!root.querySelector('fieldset').disabled);
    // A proven native rejection must recover in this same conversation, while
    // unknown/mismatched receipts keep the exact original request pinned.
    choose([new File(['correctable'],'correctable.txt',{type:'text/plain'})]);await wait(()=>root.querySelector('[aria-label="移除附件：correctable.txt"]')&&!root.querySelector('fieldset').disabled);
    change(root.querySelector('textarea'),'native validation rejects this request');
    const beforeReject=captured.length;rejectSubmit=true;root.querySelector('[aria-label="发送"]').click();await wait(()=>captured.length===beforeReject+1&&!root.querySelector('[aria-label="发送"]').disabled);
    const rejected=captured.at(-1);change(root.querySelector('textarea'),'corrected native request');
    for(const rejected_request_id of [undefined,'a-different-request']) {
      snapshotState={status:'awaiting_turn',run_state:{phase:'idle',availableActions:[]},clarification:null,rejected_request_id};
      reconnect.click();await wait(()=>!root.querySelector('fieldset').disabled&&root.querySelector('textarea').value==='corrected native request');
      root.querySelector('[aria-label="发送"]').click();await wait(()=>root.querySelector('[role="alert"]')?.textContent.includes('尚未确认'));
      check(captured.length===beforeReject+1,'Unknown or mismatched rejection receipt released the pending request');
    }
    snapshotState.rejected_request_id=rejected.request_id;reconnect.click();await wait(()=>!root.querySelector('fieldset').disabled&&!root.querySelector('[role="alert"]'));
    check(root.querySelector('textarea').value==='corrected native request'&&root.querySelector('[aria-label="移除附件：correctable.txt"]'),'Known rejection discarded editable draft or attachment');
    rejectSubmit=false;root.querySelector('[aria-label="发送"]').click();await wait(()=>captured.length===beforeReject+2&&!root.querySelector('[aria-label="停止"]'));
    check(captured.at(-1).request_id!==rejected.request_id&&captured.at(-1).message==='corrected native request'&&JSON.parse(captured.at(-1).attachments)[0].file_name==='correctable.txt','Corrected native rejection did not receive a fresh request identity in the same conversation');
    check(root.querySelector('select[aria-label="会话"]').value===fixtures[0].name,'Recovery required switching conversations');
    return {passed:['choose/remove/invalid/preview' ,'create and follow-up wire','immutable retry','owned download','conversation draft cleanup','drop and Pro image rejection','changed-option retry','delayed read object URL cleanup','snapshot recovery','flat clarification/queue/reconciling projection','same-conversation native rejection correction and unknown/mismatched receipt pinning'],submitted:captured.length,modelCalls:0,businessWrites:0,viewport:[innerWidth,innerHeight],reducedMotion:matchMedia('(prefers-reduced-motion:reduce)').matches};
  } finally { frappe.get_route=originalRoute;File.prototype.arrayBuffer=originalRead;for(const url of liveUrls)revokeUrl.call(URL,url);URL.createObjectURL=createUrl;URL.revokeObjectURL=revokeUrl;frappe.call=call;window.fetch=fetchOriginal;if(before) sessionStorage.setItem(`zebra-erpnext:selected:${frappe.session.user}`,before);else sessionStorage.removeItem(`zebra-erpnext:selected:${frappe.session.user}`); }
};
