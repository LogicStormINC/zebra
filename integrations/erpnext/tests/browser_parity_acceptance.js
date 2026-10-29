// Run in the authenticated browser with the current bundle. ALL Host RPCs and
// stream responses used below are mocked. No Task, upload, model or business write.
async () => {
  const root=document.querySelector('#zebra-erpnext-root'),originalCall=frappe.call,originalFetch=fetch,originalURL=URL.createObjectURL,originalSerialize=XMLSerializer.prototype.serializeToString,originalAnchorClick=HTMLAnchorElement.prototype.click;
  const wait=async fn=>{for(let i=0;i<240;i++){if(fn())return;await new Promise(r=>setTimeout(r,25));}throw Error('Parity UI timeout');};
  const check=(v,m)=>{if(!v)throw Error(m);};
  const change=(el,value)=>{Object.getOwnPropertyDescriptor(el instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLTextAreaElement.prototype,'value').set.call(el,value);el.dispatchEvent(new Event(el instanceof HTMLSelectElement?'change':'input',{bubbles:true}));};
  const button=label=>[...root.querySelectorAll('button')].find(el=>el.textContent.trim()===label);
  const readyButton=async label=>{await wait(()=>button(label)&&!button(label).disabled);return button(label);};
  const before=sessionStorage.getItem(`zebra-erpnext:selected:${frappe.session.user}`),captured=[],images=[],exportSVG=[],downloadNames=[],digest='a'.repeat(64);
  const fixtures=[{name:'qa-parity-a',title:'Parity QA A',company:frappe.defaults.get_user_default('Company')},{name:'qa-parity-b',title:'Parity QA B',company:frappe.defaults.get_user_default('Company')}];
  let created=0,hasAnswer=false,saved=false,feedback,delayFeedback,feedbackReply,finishDownload,cancelDownload,downloadSignal,downloadAborts=0,chartFetches=0;
  const answer=()=>({id:'qa-answer',role:'assistant',content:'legacy text should not duplicate',digest,parts:[{id:'qa-text',type:'text',format:'markdown',state:'ready',text:'# QA unique body\n\n|字段|值|\n|---|---|\n|测试|通过|\n\n[报告](artifact://private-coordinate)'},{id:'plain',type:'text',format:'plain',state:'ready',text:'plain artifact://private-coordinate body'},{id:'independent-file',type:'file',state:'ready',artifactId:'independent-file',fileName:'INDEPENDENT_FILE_MARKER.txt',mimeType:'text/plain',sizeBytes:2},{id:'independent-chart',type:'chart',state:'ready',specType:'vega-lite',specVersion:'6',title:'INDEPENDENT_CHART_MARKER',description:'独立图表不进入正文图片',specArtifactId:'chart-spec'}],sources:[{title:'Verified public source',url:'https://example.com'}],report_saved:saved,feedback});
  try {
    if(!root.querySelector('.ze-panel'))root.querySelector('.ze-launch').click();await wait(()=>root.querySelector('textarea'));
    frappe.call=function(options){
      const method=options.method.replace('zebra_erpnext.api.',''),args=options.args||{};captured.push({method,args});let message;
      if(method==='create_conversation')message=fixtures[created++%2];
      else if(method==='conversations')message=fixtures;
      else if(method==='conversation_settings')message={model_profile:'deepseek-v4-flash-executor-v1',reasoning_effort:'high',company:fixtures[0].company};
      else if(method==='snapshot')message={status:'completed',run_state:{phase:'terminal',outcome:'completed',availableActions:[]},messages:hasAnswer?[{id:'qa-user',role:'user',content:'fixture question'},answer()]:[],client_surface:null};
      else if(method==='approvals')message=[];
      else if(method==='capability_catalog')message={private_uploads:true,legacy_workspace:false,groups:[]};
      else if(method==='task_usage')message={};
      else if(method==='task_artifacts')message={artifacts:[{artifact_id:'internal',kind:'tool_output',delivery:{file_name:'internal.txt'},access:{allowed:false}},{artifact_id:'owned-id',kind:'file',delivery:{file_name:'owned.txt',mime_type:'text/plain',size_bytes:2},access:{allowed:true},retrieval:{status:'available'}}]};
      else if(method==='artifact_detail')message={artifact:{artifact_id:'owned-id',kind:'file',delivery:{file_name:'owned.txt',mime_type:'text/plain',size_bytes:2},access:{allowed:true},retrieval:{status:'available'}}};
      else if(method==='artifact_content')message={status:'ok',encoding:'base64',content_base64:'b2s=',size_bytes:2,file_name:'owned.txt',media_type:'text/plain'};
      else if(method==='submit'){hasAnswer=true;message={client_surface:null};}
      else if(method==='save_report'){saved=true;message={message_id:'qa-answer',digest,report_saved:true,feedback};}
      else if(method==='answer_feedback'){feedback=args.feedback;message={message_id:'qa-answer',digest,report_saved:saved,feedback};if(delayFeedback){feedbackReply=()=>options.callback({message});return;}}
      else throw Error('Unexpected RPC blocked in parity fixture: '+method);
      queueMicrotask(()=>options.callback({message}));return Promise.resolve({message});
    };
    window.fetch=async(input,init)=>{
      const url=String(input);
      if(url.startsWith('/api/method/zebra_erpnext.api.events?'))return new Response('data: {"type":"RUN_FINISHED"}\n\n',{headers:{'Content-Type':'text/event-stream'}});
      if(url.startsWith('/api/method/zebra_erpnext.api.artifact_preview?')&&new URL(url,location.origin).searchParams.get('artifact_id')==='chart-spec'){chartFetches++;return new Response(JSON.stringify({data:{values:[{label:'QA',value:1}]},mark:'bar',encoding:{x:{field:'label',type:'nominal'},y:{field:'value',type:'quantitative'}}}),{headers:{'Content-Type':'application/json'}});}
      if(url.startsWith('/api/method/zebra_erpnext.api.artifact_download?')) {
        if(new URL(url,location.origin).searchParams.get('artifact_id')==='independent-file')return new Promise((resolve,reject)=>{downloadSignal=init.signal;finishDownload=()=>resolve(new Response('ok',{headers:{'Content-Type':'application/octet-stream'}}));cancelDownload=()=>reject(new DOMException('Fixture cleanup','AbortError'));init.signal.addEventListener('abort',()=>{downloadAborts++;reject(new DOMException('Aborted','AbortError'));},{once:true});});
        return new Response('ok',{headers:{'Content-Type':'application/octet-stream'}});
      }
      return originalFetch(input,init);
    };
    HTMLAnchorElement.prototype.click=function(){if(this.href.startsWith('blob:')){downloadNames.push(this.download);return;}return originalAnchorClick.call(this);};
    URL.createObjectURL=function(blob){if(blob.type==='image/png')images.push(blob);return originalURL.call(this,blob);};
    XMLSerializer.prototype.serializeToString=function(node){const value=originalSerialize.call(this,node);if(value.includes('ze-share-card'))exportSVG.push(value);return value;};
    const newChat=()=>{const create=root.querySelector('.ze-create')||[...root.querySelectorAll('.ze-controls button')].find(el=>el.textContent==='新建');create.click();};
    newChat();await wait(()=>root.querySelector('select[aria-label="会话"]')?.value===fixtures[0].name&&!root.querySelector('fieldset').disabled);
    change(root.querySelector('textarea'),'unsent draft');
    const transfer=new DataTransfer();transfer.items.add(new File(['draft private file'],'keep.txt',{type:'text/plain'}));
    const input=root.querySelector('input[type=file]');input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>root.querySelector('[aria-label="移除附件：keep.txt"]')&&!root.querySelector('fieldset').disabled);
    const chip=root.querySelector('.zebra-agent-composer__suggestions button');check(chip,'Welcome composer recommendation missing');chip.click();chip.click();
    await wait(()=>captured.filter(row=>row.method==='submit').length===1&&button('保存报告'));
    const first=captured.find(row=>row.method==='submit');check(first.args.message!=='unsent draft'&&JSON.parse(first.args.attachments).length===0,'Suggestion sent draft or attached private file');
    check(root.querySelector('textarea').value==='unsent draft'&&root.querySelector('[aria-label="移除附件：keep.txt"]'),'Suggestion discarded draft/files');
    check(root.querySelectorAll('.ze-answer h1').length===1&&!root.textContent.includes('legacy text should not duplicate'),'Text parts duplicated/lost visible body');
    check(!root.querySelector('.ze-answer').textContent.includes('artifact://')&&root.querySelector('.ze-answer').textContent.includes('INDEPENDENT_FILE_MARKER'),'Mixed public Parts missing or native URI leaked in plain text');
    check(root.querySelector('.ze-sources a')?.href==='https://example.com/','Source lost');
    check(root.querySelectorAll('.ze-inline-files .ze-file-card').length===1&&!root.querySelector('.ze-inline-files').textContent.includes('internal.txt'),'Internal trace displayed as file');
    await wait(()=>chartFetches===1&&root.querySelector('.zebra-agent-chart__canvas svg'));
    const chartSVG=root.querySelector('.zebra-agent-chart__canvas svg'),chartFetchBaseline=chartFetches;
    const fileDownload=root.querySelector('.ze-answer [aria-label="下载 INDEPENDENT_FILE_MARKER.txt"]');fileDownload.click();await wait(()=>finishDownload);
    change(root.querySelector('textarea'),'unsent draft while downloading');await wait(()=>root.querySelector('textarea').value==='unsent draft while downloading');
    check(!downloadSignal.aborted&&downloadAborts===0&&fileDownload===root.querySelector('.ze-answer [aria-label="下载 INDEPENDENT_FILE_MARKER.txt"]')&&fileDownload.textContent==='下载中','Typing remounted the inline FileCard or aborted its download');
    change(root.querySelector('textarea'),'unsent draft');
    root.querySelector('.ze-inline-files [aria-label="预览 owned.txt"]').click();await wait(()=>root.querySelector('.ze-inline-files .zebra-agent-asset-preview'));
    const save=await readyButton('保存报告');save.click();save.click();await wait(()=>[...root.querySelectorAll('a')].some(el=>el.textContent==='查看已保存报告'));
    check(captured.filter(row=>row.method==='save_report').length===1,'Double report save sent duplicate RPC');
    root.querySelector('.ze-more-actions').open=true;(await readyButton('有帮助')).click();await wait(()=>button('有帮助').getAttribute('aria-pressed')==='true');
    check(!downloadSignal.aborted&&downloadAborts===0&&fileDownload===root.querySelector('.ze-answer [aria-label="下载 INDEPENDENT_FILE_MARKER.txt"]'),'Answer notice update cancelled/remounted inline download');
    check(chartFetches===chartFetchBaseline&&chartSVG===root.querySelector('.zebra-agent-chart__canvas svg'),'Typing or answer notice update re-fetched/reset the existing chart');
    finishDownload();await wait(()=>downloadNames.includes('INDEPENDENT_FILE_MARKER.txt'));
    check(downloadAborts===0,'Delayed inline download was aborted before completion');
    (await readyButton('导出图片')).click();await wait(()=>images.length===1);
    const bitmap=await createImageBitmap(images[0]);check(bitmap.width===960&&bitmap.height>100,'Image failed decode');
    const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;const context=canvas.getContext('2d');context.drawImage(bitmap,0,0);
    const pixels=context.getImageData(0,0,canvas.width,canvas.height).data;let dark=0;for(let i=0;i<pixels.length;i+=4)if(pixels[i+3]>0&&pixels[i]<120&&pixels[i+1]<120&&pixels[i+2]<120)dark++;
    check(dark>200,'Exported image is blank');bitmap.close();
    check(exportSVG.length>0&&exportSVG.every(value=>value.includes('QA unique body')&&!value.includes('INDEPENDENT_FILE_MARKER')&&!value.includes('INDEPENDENT_CHART_MARKER')&&!value.includes('artifact://')),'PNG capture included an independent file/chart or private artifact URI');
    (await readyButton('重新处理')).click();check(captured.filter(row=>row.method==='submit').length===1,'Regeneration ran before confirmation');(await readyButton('确认重新处理')).click();
    await wait(()=>captured.filter(row=>row.method==='submit').length===2&&!root.querySelector('[aria-label="停止"]'));
    check(captured.filter(row=>row.method==='submit')[1].args.message==='fixture question'&&JSON.parse(captured.filter(row=>row.method==='submit')[1].args.attachments).length===0,'Regeneration reuploaded attachments or changed request');
    check(root.querySelector('textarea').value==='unsent draft'&&root.querySelector('[aria-label="移除附件：keep.txt"]'),'Regeneration discarded unsent draft');
    root.querySelector('.ze-more-actions').open=true;delayFeedback=true;(await readyButton('需改进')).click();await wait(()=>feedbackReply);
    newChat();await wait(()=>root.querySelector('select[aria-label="会话"]')?.value===fixtures[1].name);feedbackReply();await new Promise(r=>setTimeout(r,60));
    check(!root.textContent.includes('反馈已保存'),'Delayed old-conversation feedback acknowledgement leaked');
    return {passed:['welcome recommendation exact-once submit','draft/file preservation','text-parts body without duplication','public sources','real file cards/internal trace filter','owned preview','delayed inline download survives typing and answer notices','chart fetch/view stable across unrelated renders','idempotent report UI','persistent feedback UI','decoded nonblank text-only image excluding mixed file/chart Parts','explicit regeneration without file replay','conversation switch acknowledgement guard'],hostWrites:0,modelCalls:0,businessWrites:0};
  } finally {cancelDownload?.();HTMLAnchorElement.prototype.click=originalAnchorClick;XMLSerializer.prototype.serializeToString=originalSerialize;frappe.call=originalCall;window.fetch=originalFetch;URL.createObjectURL=originalURL;if(before)sessionStorage.setItem(`zebra-erpnext:selected:${frappe.session.user}`,before);else sessionStorage.removeItem(`zebra-erpnext:selected:${frappe.session.user}`);}
};
