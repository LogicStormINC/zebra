import { gsap } from 'gsap';
import { Flip } from 'gsap/Flip';

gsap.registerPlugin(Flip);
export { gsap, Flip };
export const motionAllowed = () => !window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// One Agent-scoped controller covers shared SDK children without changing the SDK.
export function installAgentMotion(root: HTMLElement) {
  const media = window.matchMedia('(prefers-reduced-motion: reduce)');
  const seen = new WeakSet<Element>();
  const targets = new Set<Element>();
  const reveals = '.ze-sidebar,.ze-drawer,.ze-welcome,.zebra-agent-composer';
  const own = (node: EventTarget | null) => node instanceof Element ? node.closest('#zebra-erpnext-root,[data-ze-agent-dialog]') : null;
  const control = (node: EventTarget | null) => own(node) && node instanceof Element ? node.closest<HTMLElement>('button,summary,select') : null;
  function tween(target: Element, vars: gsap.TweenVars) {
    if (media.matches || !target.isConnected) return;
    targets.add(target);
    gsap.to(target, { duration: .16, ease: 'power2.out', overwrite: 'auto', ...vars });
  }
  function reveal(nodes: Element[]) {
    const fresh = nodes.filter(node => { if (seen.has(node)) return false; seen.add(node); return true; });
    if (media.matches) return;
    // ponytail: animate visible additions only, capped at 12 per DOM batch; old
    // history and token text edits stay still. Use virtualization for huge histories.
    fresh.filter(node => { const r = node.getBoundingClientRect(); return r.width && r.height && r.bottom > 0 && r.top < innerHeight; }).slice(-12).forEach((node, i) => {
      targets.add(node);
      gsap.fromTo(node, { opacity: 0, x: node.matches('.ze-sidebar') ? -18 : 0, y: node.matches('.ze-sidebar') ? 0 : 8 },
        { opacity: 1, x: 0, y: 0, duration: .24, delay: Math.min(i * .018, .10), ease: 'power2.out', overwrite: 'auto', clearProps: 'transform,opacity' });
    });
  }
  const observer = new MutationObserver(records => {
    const additions: Element[] = [];
    for (const record of records) {
      if (record.type === 'childList') for (const node of record.addedNodes) if (node instanceof Element) {
        if (node.matches(reveals)) additions.push(node);
        additions.push(...node.querySelectorAll(reveals));
      }
      if (record.type === 'attributes' && record.target instanceof Element) {
        const node = record.target;
        if (record.attributeName === 'open' && node instanceof HTMLDetailsElement && node.open) {
          const content = Array.from(node.children).find(child => child.tagName !== 'SUMMARY');
          if (content && !media.matches) { targets.add(content); gsap.fromTo(content, { y: -4, opacity: 0 }, { y: 0, opacity: 1, duration: .18, clearProps: 'transform,opacity', overwrite: true }); }
        }

      }
    }
    for (const node of targets) if (!node.isConnected) { gsap.killTweensOf(node); targets.delete(node); }
    reveal(additions);
  });
  observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['open'] });
  const hover = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return;
    const node = control(event.target);
    if (!node || node.matches(':disabled') || (event.relatedTarget instanceof Node && node.contains(event.relatedTarget))) return;
    tween(node, event.type === 'pointerover' ? { y: -1, scale: 1.015 } : { y: 0, scale: 1, clearProps: 'transform' });
  };
  const press = (event: PointerEvent) => {
    const node = control(event.target);
    if (node && !node.matches(':disabled')) tween(node, event.type === 'pointerdown' ? { scale: .97, duration: .09 } : { scale: 1, y: 0, clearProps: 'transform' });
  };
  const focus = (event: FocusEvent) => {
    if (!own(event.target) || !(event.target instanceof Element)) return;
    const composer = event.target.closest('.zebra-agent-composer');
    if (!composer || (event.relatedTarget instanceof Node && composer.contains(event.relatedTarget))) return;
    tween(composer, event.type === 'focusin' ? { boxShadow: '0 0 0 2px rgba(21,125,101,0.15)' } : { boxShadow: '0 8px 24px rgba(0,0,0,0.08)', clearProps: 'boxShadow' });
  };
  const change = (event: Event) => { if (own(event.target) && event.target instanceof HTMLSelectElement && !media.matches) { targets.add(event.target); gsap.fromTo(event.target, { opacity: .45 }, { opacity: 1, duration: .2, clearProps: 'opacity', overwrite: 'auto' }); } };
  const listeners: [string, EventListener][] = [['pointerover', hover as EventListener], ['pointerout', hover as EventListener], ['pointerdown', press as EventListener], ['pointerup', press as EventListener], ['pointercancel', press as EventListener], ['focusin', focus as EventListener], ['focusout', focus as EventListener], ['change', change]];
  for (const [type, listener] of listeners) document.addEventListener(type, listener);
  function settle() {
    if (!media.matches) return;
    // Finish exits and Flip callbacks as well, so preference changes cannot strand
    // an invisible mounted panel or a partially transformed layout.
    const nodes = [...root.querySelectorAll('*'), ...document.querySelectorAll('[data-ze-agent-dialog] *')];
    for (const animation of gsap.getTweensOf(nodes)) animation.totalProgress(1);
    Flip.killFlipsOf(nodes, true);
    gsap.set([...targets], { clearProps: 'transform,opacity,boxShadow' });
  }
  media.addEventListener('change', settle);
  reveal([...root.querySelectorAll(reveals)]);
  if (motionAllowed()) gsap.fromTo(root.querySelector('.ze-launch'), { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: .25, clearProps: 'transform,opacity' });
  return () => {
    observer.disconnect(); media.removeEventListener('change', settle);
    for (const [type, listener] of listeners) document.removeEventListener(type, listener);
    gsap.killTweensOf([...targets]); gsap.set([...targets], { clearProps: 'transform,opacity,boxShadow' }); targets.clear();
  };
}

export function animateAgentDialog(dialog: any) {
  const wrapper = dialog?.$wrapper?.[0];
  if (!wrapper) return;
  wrapper.setAttribute('data-ze-agent-dialog', '');
  const content = wrapper.querySelector('.modal-content');
  if (content && motionAllowed()) gsap.fromTo(content, { y: 12, opacity: 0 }, { y: 0, opacity: 1, duration: .24, ease: 'power2.out', clearProps: 'transform,opacity' });
  dialog.$wrapper.one('hidden.bs.modal', () => gsap.killTweensOf(wrapper.querySelectorAll('*')));
}
