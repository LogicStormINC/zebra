import React from 'react';
import { ShieldIcon } from './icons';

/** Chrome around the chat composer: elevation card + an honest safety footnote. */
export function ComposerDock({ children, note }: { children: React.ReactNode; note?: string }) {
  return <div className="ze-composer-dock">
    {children}
    <p className="ze-composer-note"><ShieldIcon size={12} />{note || '写入与审核由你把控 · 涉及业务修改需人工确认'}</p>
  </div>;
}
