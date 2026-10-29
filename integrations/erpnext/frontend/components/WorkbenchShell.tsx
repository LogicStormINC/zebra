import React from 'react';

/**
 * Fullscreen workbench frame: optional session rail on the left (with a mobile
 * backdrop), the workspace column on the right. Structure only — content and
 * behaviour come from the container through slots.
 */
export function WorkbenchShell({ sidebarOpen, sidebar, onSidebarClose, mainInert, sidebarInert, children }: {
  sidebarOpen: boolean;
  sidebar: React.ReactNode;
  onSidebarClose: () => void;
  mainInert: boolean;
  sidebarInert: boolean;
  children: React.ReactNode;
}) {
  return <>
    {sidebarOpen && <>
      <button className="ze-sidebar-backdrop" aria-label="收起会话列表" onClick={onSidebarClose} />
      <div inert={sidebarInert || undefined} className="ze-sidebar-host">{sidebar}</div>
    </>}
    <div className="ze-main" inert={mainInert || undefined}>{children}</div>
  </>;
}
