// Chrome evaluate_script, authenticated ERPNext. No model calls or business writes.
// Run normally and with prefersReducedMotion='reduce'. Local DOM probes are removed.
async () => {
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const pause=ms=>new Promise(r=>setTimeout(r,ms));
  const check=(v,m)=>{if(!v)throw Error(m);};
  const wait=async fn=>{for(let i=0;i<100;i++){if(fn())return;await pause(20);}throw Error('Motion UI timeout');};
  await wait(()=>document.querySelector('#zebra-erpnext-root .ze-launch'));
  const root=document.querySelector('#zebra-erpnext-root');
  root.querySelector('.ze-panel [aria-label="关闭助手"]')?.click();await wait(()=>!root.querySelector('.ze-panel'));
  root.querySelector('.ze-launch').click();await wait(()=>root.querySelector('.ze-panel'));
  await pause(40);const panel=root.querySelector('.ze-panel'), entering=Number(getComputedStyle(panel).opacity);
  check(reduced ? entering===1 : entering<1,'Entrance did not honor motion preference');
  await pause(350);check(getComputedStyle(panel).opacity==='1'&&getComputedStyle(panel).transform==='none','Panel failed to settle');
  if(!root.querySelector('.ze-panel-fullscreen'))root.querySelector('[data-ze-fullscreen]').click();
  await pause(400);const box=panel.getBoundingClientRect();
  check(Math.abs(box.width-innerWidth)<2&&Math.abs(box.height-innerHeight)<2,'Fullscreen Flip left stale bounds');
  if(!root.querySelector('.ze-sidebar'))root.querySelector('[aria-label="展开会话列表"]').click();await pause(400);
  root.querySelector('.ze-sidebar header button').click();await pause(520);check(!root.querySelector('.ze-sidebar'),'Sidebar exit did not unmount');
  root.querySelector('[aria-label="展开会话列表"]').click();await pause(400);check(root.querySelector('.ze-sidebar'),'Sidebar failed to return');
  const probe=document.createElement('div');probe.className='zebra-agent-message';probe.textContent='本地动效验收';
  const status=document.createElement('div');status.className='ze-note';status.textContent='本地提示动效验收';
  const main=root.querySelector('.ze-main');main.prepend(probe,status);
  try {
    await pause(40);const opacity=Number(getComputedStyle(probe).opacity);
    check(reduced ? opacity===1 : opacity<1,'Message entrance missing');
    await pause(350);let styleChanges=0;const observer=new MutationObserver(records=>styleChanges+=records.length);
    observer.observe(probe,{attributes:true,attributeFilter:['style']});
    for(let i=0;i<30;i++)probe.firstChild.appendData('字');await pause(300);observer.disconnect();
    check(styleChanges===0,'Streaming text restarted message animation');
    const control=root.querySelector('[data-ze-fullscreen]');
    control.dispatchEvent(new PointerEvent('pointerover',{bubbles:true,pointerType:'mouse'}));await pause(50);
    check(reduced ? getComputedStyle(control).transform==='none' : getComputedStyle(control).transform!=='none','Hover feedback mismatch');
    control.dispatchEvent(new PointerEvent('pointerout',{bubbles:true,pointerType:'mouse'}));await pause(220);
    check(getComputedStyle(control).transform==='none','Hover transform not cleared');
    const menu=root.querySelector('.ze-session-menu');
    if(menu){menu.querySelector('summary').click();await pause(220);menu.querySelector('button').click();await pause(400);const modal=document.querySelector('[data-ze-agent-dialog].modal.show');check(modal,'Rename dialog is outside Agent motion scope');modal.querySelector('.btn-modal-close').click();await pause(400);}
    // Rapid reversible layout operations must settle in the final requested mode.
    control.click();await pause(30);control.click();await pause(400);
    check(root.querySelector('.ze-panel-fullscreen')&&getComputedStyle(panel).transform==='none','Rapid Flip left a transform');
    root.querySelector('[aria-label="关闭助手"]').click();await pause(30);
    if(!reduced)check(root.querySelector('.ze-panel'),'Exit was not animated');
    await pause(250);check(!root.querySelector('.ze-panel'),'Exit left an invisible panel');
    root.querySelector('.ze-launch').click();await pause(350);check(getComputedStyle(root.querySelector('.ze-panel')).opacity==='1','Panel cannot reopen');
    return {reduced,entrance:true,exit:true,fullscreen:true,sidebar:true,messageEntrance:true,streamTokensStable:true,hover:true,dialogs:true,rapidToggle:true};
  } finally {probe.remove();status.remove();}
}
