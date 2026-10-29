// Run as a function with Chrome DevTools evaluate_script on an authenticated ERPNext page.
// Snapshot/approval replies are replaced in this tab only; no model call or business write.
async () => {
  const root = document.querySelector('#zebra-erpnext-root');
  const check = (value, message) => { if (!value) throw new Error(message); };
  const wait = async predicate => { for (let n = 0; n < 80; n++) { if (predicate()) return; await new Promise(r => setTimeout(r, 50)); } throw new Error('UI check timed out'); };
  if (!root.querySelector('.ze-panel')) root.querySelector('.ze-launch').click();
  await wait(() => root.querySelector('select[aria-label="会话"] option[value]:not([value=""])'));
  const original = frappe.call;
  const markdown = '# Markdown 验收\n\n**加粗**与 `行内代码`\n\n- 第一项\n- 第二项\n\n| 项目 | 值 |\n| --- | --- |\n| 币种 | CNY |\n\n```python\nprint("你好")\n```\n\n> 引用\n\n[安全链接](https://example.com)\n\n[危险链接](javascript:alert(1))\n\n<img src="/missing-qa-image" onerror="window.__zebraXss=1"><script>window.__zebraXss=1</script>';
  try {
    frappe.call = function (...args) {
      const options = args[0];
      if (options?.method === 'zebra_erpnext.api.snapshot' || options?.method === 'zebra_erpnext.api.approvals') {
        const message = options.method.endsWith('.approvals') ? [] : { status: 'awaiting_turn', messages: [
          { id: 'qa-user', role: 'user', content: '# 用户原文不转换' },
          { id: 'qa-markdown', role: 'assistant', content: markdown }
        ], client_surface: null };
        queueMicrotask(() => options.callback({ message }));
        return Promise.resolve({ message });
      }
      return original.apply(this, args);
    };
    const select = root.querySelector('select[aria-label="会话"]');
    select.value = [...select.options].find(x => x.value).value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    await wait(() => root.querySelector('.ze-markdown table'));
    const rendered = root.querySelector('.ze-markdown');
    check(rendered.querySelector('h1')?.textContent === 'Markdown 验收', 'Heading not rendered');
    check(rendered.querySelector('strong')?.textContent === '加粗', 'Bold not rendered');
    check(rendered.querySelector('ul li') && rendered.querySelector('blockquote'), 'List/quote not rendered');
    check(rendered.querySelector('pre code')?.textContent.includes('print("你好")'), 'Code fence not rendered');
    check(!rendered.querySelector('script,iframe,[onerror],a[href^="javascript:"]') && !window.__zebraXss, 'Unsafe HTML survived');
    check(getComputedStyle(rendered).whiteSpace === 'normal', 'Markdown inherited plain-text whitespace');
    const before = document.body.style.overflow;
    root.querySelector('[data-ze-fullscreen]').click();
    await wait(() => root.querySelector('.ze-panel-fullscreen'));
    await new Promise(resolve => setTimeout(resolve, 400)); // settle GSAP fullscreen Flip
    const panel = root.querySelector('.ze-panel');
    const box = panel.getBoundingClientRect();
    check(box.x === 0 && box.y === 0 && Math.abs(box.width - innerWidth) < 2 && Math.abs(box.height - innerHeight) < 2, 'Fullscreen does not cover viewport');
    check(panel.getAttribute('aria-modal') === 'true' && document.body.style.overflow === 'hidden', 'Fullscreen accessibility/scroll lock missing');
    const controls = [...panel.querySelectorAll('button:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]')].filter(x => x.getClientRects().length);
    controls.at(-1).focus();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }));
    check(document.activeElement === controls[0], 'Fullscreen tab focus escaped');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await wait(() => !root.querySelector('.ze-panel-fullscreen'));
    check(root.querySelector('.ze-panel') && document.body.style.overflow === before, 'Escape did not restore side panel/scroll');
    check(root.querySelector('.ze-markdown table'), 'Mode switch lost messages');
    return { passed: ['headings/bold/lists/tables/code/quotes', 'unsafe HTML and URL rejection', 'viewport fullscreen', 'keyboard focus and Escape', 'messages preserved'], viewport: [innerWidth, innerHeight], fullscreen: { width: box.width, height: box.height } };
  } finally { frappe.call = original; }
}
