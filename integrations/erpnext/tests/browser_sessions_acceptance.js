// Run with Chrome DevTools evaluate_script on an authenticated ERPNext page.
// Creates two empty QA conversations, exercises real CRUD, removes both in finally.
async () => {
  const check = (v, m) => { if (!v) throw Error(m); };
  const wait = async fn => { for (let i=0;i<120;i++) { if(fn()) return; await new Promise(r=>setTimeout(r,50)); } throw Error('UI timeout'); };
  const rpc = async (method,args={}) => { const r=await fetch('/api/method/zebra_erpnext.api.'+method,{method:'POST',headers:{'Content-Type':'application/json','X-Frappe-CSRF-Token':frappe.csrf_token},body:JSON.stringify(args)}); const data=await r.json(); if(!r.ok||data.exc) throw Error(method+' failed'); return data.message; };
  const root=document.querySelector('#zebra-erpnext-root'); const fixtures=[];
  const renamed='侧栏验收 '+Date.now();
  try {
    if(!root.querySelector('.ze-panel')) root.querySelector('.ze-launch').click();
    await wait(()=>root.querySelector('[data-ze-fullscreen]'));
    if(!root.querySelector('.ze-panel-fullscreen')) root.querySelector('[data-ze-fullscreen]').click();
    await wait(()=>root.querySelector('.ze-sidebar'));
    const before=new Set((await rpc('conversations')).map(x=>x.name));
    root.querySelector('.ze-create').click();
    await wait(()=>root.querySelector('.ze-session.is-selected'));
    let rows=await rpc('conversations'); let first=rows.find(x=>!before.has(x.name));
    check(first,'UI create did not persist'); fixtures.push(first.name);
    const selected=()=>root.querySelector('.ze-session.is-selected');
    selected().querySelector('summary').click(); selected().querySelector('.ze-session-menu button').click();
    await wait(()=>document.querySelector('.modal.show input[data-fieldname="title"]'));
    const input=document.querySelector('.modal.show input[data-fieldname="title"]'); input.value=renamed; input.dispatchEvent(new Event('change',{bubbles:true}));
    await new Promise(r=>setTimeout(r,400));
    [...document.querySelectorAll('.modal.show .btn-modal-primary')].at(-1).click();
    await wait(()=>selected()?.textContent.includes(renamed));
    check((await rpc('conversations')).find(x=>x.name===first.name).title===renamed,'Rename not durable');
    root.querySelector('.ze-create').click();
    await wait(()=>!selected()?.textContent.includes(renamed));
    rows=await rpc('conversations'); const second=rows.find(x=>!before.has(x.name)&&x.name!==first.name); check(second,'Second create failed'); fixtures.push(second.name);
    [...root.querySelectorAll('.ze-session-select')].find(x=>x.title===renamed).click();
    await wait(()=>selected()?.textContent.includes(renamed));
    const panel=root.querySelector('.ze-panel').getBoundingClientRect(), side=root.querySelector('.ze-sidebar').getBoundingClientRect(), main=root.querySelector('.ze-main').getBoundingClientRect();
    check(side.left===panel.left && main.left>=side.right-1 && main.width>500,'Not a two-pane layout');
    selected().querySelector('summary').click(); selected().querySelectorAll('.ze-session-menu button')[1].click();
    await wait(()=>document.querySelector('.modal.show .btn-modal-primary'));
    await new Promise(r=>setTimeout(r,400));
    [...document.querySelectorAll('.modal.show .btn-modal-primary')].at(-1).click();
    await wait(()=>![...root.querySelectorAll('.ze-session-select')].some(x=>x.title===renamed));
    check(!(await rpc('conversations')).some(x=>x.name===first.name),'Deleted conversation still listed');
    const denied=await fetch('/api/method/zebra_erpnext.api.snapshot?conversation='+first.name); check(denied.status===403,'Deleted history remains accessible');
    return {create:true,switch:true,renamePersisted:true,delete:true,deletedAccessDenied:true,sidebarWidth:side.width,chatWidth:main.width};
  } finally {
    for(const name of fixtures) { try {await rpc('delete_conversation',{conversation:name});} catch {} }
  }
}
