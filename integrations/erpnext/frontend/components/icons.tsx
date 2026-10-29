import React from 'react';

// Inline SVG icon set (Phosphor-inspired geometry). Kept dependency-free on purpose:
// the ERP host may run on an offline LAN, so CDN icon fonts are not an option.
type IconProps = { className?: string; size?: number };
function svg(props: IconProps, children: React.ReactNode, stroke = true) {
  return <svg className={props.className} width={props.size || 16} height={props.size || 16} viewBox="0 0 24 24"
    fill={stroke ? 'none' : 'currentColor'} stroke={stroke ? 'currentColor' : 'none'} strokeWidth={stroke ? 1.8 : undefined}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}
export const SparkleIcon = (p: IconProps) => svg(p, <path d="M12 2l2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4L12 2z" fill="currentColor" stroke="none" />, false);
export const AsteriskIcon = (p: IconProps) => svg(p, <path d="M12 3v18M4.2 7.5l15.6 9M19.8 7.5l-15.6 9" strokeWidth={2.4} />);
export const PlusIcon = (p: IconProps) => svg(p, <path d="M12 5v14M5 12h14" />);
export const SearchIcon = (p: IconProps) => svg(p, <><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></>);
export const CloseIcon = (p: IconProps) => svg(p, <path d="M6 6l12 12M18 6L6 18" />);
export const CaretDownIcon = (p: IconProps) => svg(p, <path d="M6 9l6 6 6-6" />);
export const CaretRightIcon = (p: IconProps) => svg(p, <path d="M9 6l6 6-6 6" />);
export const SidebarIcon = (p: IconProps) => svg(p, <><rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M9.5 4v16" /></>);
export const ExpandIcon = (p: IconProps) => svg(p, <><path d="M9 4H4v5M15 20h5v-5" /><path d="M4 4l5.5 5.5M20 20l-5.5-5.5" /></>);
export const CollapseIcon = (p: IconProps) => svg(p, <><path d="M4 9h5V4M20 15h-5v5" /><path d="M9 9L4 4M15 15l5 5" /></>);
export const PinIcon = (p: IconProps) => svg(p, <path d="M6 3.5h12V21l-6-3.8L6 21z" />);
export const GearIcon = (p: IconProps) => svg(p, <><path d="M4 7h16M4 12h16M4 17h16" /><circle cx="9.5" cy="7" r="1.9" fill="currentColor" stroke="none" /><circle cx="15" cy="12" r="1.9" fill="currentColor" stroke="none" /><circle cx="8" cy="17" r="1.9" fill="currentColor" stroke="none" /></>);
export const MemoryIcon = (p: IconProps) => svg(p, <><rect x="6.5" y="6.5" width="11" height="11" rx="2.5" /><path d="M12 3v3.5M12 17.5V21M3 12h3.5M17.5 12H21M8 3v3.5M16 3v3.5M8 17.5V21M16 17.5V21" /></>);
export const CheckCircleIcon = (p: IconProps) => svg(p, <><circle cx="12" cy="12" r="9" /><path d="M8.5 12.4l2.4 2.4 4.6-5.2" /></>);
export const ClockIcon = (p: IconProps) => svg(p, <><circle cx="12" cy="12" r="9" /><path d="M12 7.5V12l3 2.2" /></>);
export const DotsIcon = (p: IconProps) => svg(p, <><circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" /></>, false);
export const ChatIcon = (p: IconProps) => svg(p, <><path d="M21 12a8.5 8.5 0 01-8.5 8.5c-1.5 0-3-.4-4.2-1.1L3 21l1.6-5.3A8.5 8.5 0 1121 12z" /><circle cx="8.7" cy="12" r="1.1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" /><circle cx="15.3" cy="12" r="1.1" fill="currentColor" stroke="none" /></>);
export const DatabaseIcon = (p: IconProps) => svg(p, <><ellipse cx="12" cy="5.5" rx="8" ry="3" /><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></>);
export const PaperclipIcon = (p: IconProps) => svg(p, <path d="M20 11.4l-8.5 8.5a4.8 4.8 0 01-6.8-6.8l8.5-8.5a3.4 3.4 0 014.8 4.8L9.5 17.9a2 2 0 01-2.9-2.9l8.6-8.5" />);
export const SendIcon = (p: IconProps) => svg(p, <path d="M12 19V5M5.5 11.5L12 5l6.5 6.5" />);
export const ShieldIcon = (p: IconProps) => svg(p, <><path d="M12 3l7.5 3v5.2c0 4.9-3.8 8-7.5 9.8-3.7-1.8-7.5-4.9-7.5-9.8V6z" /><path d="M9 12l2.1 2.1L15.4 9.6" /></>);
export const InfoIcon = (p: IconProps) => svg(p, <><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><circle cx="12" cy="7.7" r="1.1" fill="currentColor" stroke="none" /></>);
export const WarningIcon = (p: IconProps) => svg(p, <><path d="M12 4L2.8 20h18.4z" /><path d="M12 10v4.2" /><circle cx="12" cy="17" r="1" fill="currentColor" stroke="none" /></>);
export const PenIcon = (p: IconProps) => svg(p, <><path d="M4 20l4.3-1.1L19.6 7.6a2.1 2.1 0 00-3-3L5.3 15.9z" /><path d="M13.9 6.7l3 3" /></>);
export const ProhibitIcon = (p: IconProps) => svg(p, <><circle cx="12" cy="12" r="9" /><path d="M8.5 8.5l7 7M15.5 8.5l-7 7" /></>);
export const ListIcon = (p: IconProps) => svg(p, <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />);
export const BookIcon = (p: IconProps) => svg(p, <><path d="M4 5.5A2.5 2.5 0 016.5 3H20v15H6.5A2.5 2.5 0 004 20.5z" /><path d="M4 5.5v15" /></>);
export const PuzzleIcon = (p: IconProps) => svg(p, <><path d="M10 4.5a2 2 0 114 0V6h2.2a1.8 1.8 0 011.8 1.8V10h1.5a2 2 0 110 4H18v2.2a1.8 1.8 0 01-1.8 1.8H14v1.5a2 2 0 11-4 0V18H7.8A1.8 1.8 0 016 16.2V14H4.5a2 2 0 110-4H6V7.8A1.8 1.8 0 017.8 6H10z" /></>);
export const PlugIcon = (p: IconProps) => svg(p, <><path d="M9 3v5M15 3v5" /><path d="M6 8h12v3a6 6 0 01-6 6 6 6 0 01-6-6z" /><path d="M12 17v4" /></>);
export const RefreshIcon = (p: IconProps) => svg(p, <><path d="M20 11a8 8 0 10-2.3 6.3" /><path d="M20 4v7h-7" /></>);
export const FilterIcon = (p: IconProps) => svg(p, <path d="M4 6h16M7 12h10M10 18h4" />);
export const SlidersIcon = (p: IconProps) => svg(p, <><path d="M5 5v14M12 5v14M19 5v14" /><circle cx="5" cy="9" r="2.1" fill="currentColor" stroke="none" /><circle cx="12" cy="15" r="2.1" fill="currentColor" stroke="none" /><circle cx="19" cy="8" r="2.1" fill="currentColor" stroke="none" /></>);
