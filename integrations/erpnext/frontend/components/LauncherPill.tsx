import React from 'react';
import { ZEBRA_LOGO } from './logo';

/** Floating summon pill, always-available entry point on ERP pages. */
export function LauncherPill({ hidden, open, onToggle }: { hidden?: boolean; open: boolean; onToggle: () => void }) {
  return <button hidden={hidden} className="ze-launch" aria-label={open ? '关闭 zebra 助手' : '打开 zebra 助手'} aria-expanded={open} onClick={onToggle}>
    <span className="ze-logo-chip" aria-hidden="true"><img src={ZEBRA_LOGO} alt="" /></span>
    <span className="ze-launch-word">zebra</span>
  </button>;
}
