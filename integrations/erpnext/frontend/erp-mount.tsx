import React, { type ComponentType } from 'react';
import { createRoot } from 'react-dom/client';

export function mountErpPanel(Panel: ComponentType) {
  function mount() {
    if (window.__zebraERP || !window.frappe?.boot || window.frappe.session?.user === 'Guest' || !/^\/(desk|app)(\/|$)/.test(location.pathname)) return;
    window.__zebraERP = true;
    const root = document.createElement('div'); root.id = 'zebra-erpnext-root'; document.body.append(root); createRoot(root).render(<Panel />);
  }
  if (window.frappe?.ready) window.frappe.ready(mount);
  const readyTimer = setInterval(() => { mount(); if (window.__zebraERP) clearInterval(readyTimer); }, 500);
}
