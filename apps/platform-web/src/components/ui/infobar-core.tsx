'use client';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useIsMobile } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';
import { mergeProps } from '@base-ui/react/merge-props';
import { useRender } from '@base-ui/react/use-render';
import { VariantProps, cva } from 'class-variance-authority';
import { Icons } from '@/components/icons';
import { usePathname } from 'next/navigation';
import * as React from 'react';

const INFOBAR_WIDTH = '22rem';
const INFOBAR_WIDTH_MOBILE = '22rem';
const INFOBAR_WIDTH_ICON = '3rem';
const INFOBAR_KEYBOARD_SHORTCUT = 'i';

export type HelpfulLink = {
  title: string;
  url: string;
};

export type DescriptiveSection = {
  title: string;
  description: string;
  links?: HelpfulLink[];
};

export type InfobarContent = {
  title: string;
  sections: DescriptiveSection[];
};

type InfobarContextProps = {
  state: 'expanded' | 'collapsed';
  open: boolean;
  setOpen: (open: boolean) => void;
  openMobile: boolean;
  setOpenMobile: (open: boolean) => void;
  isMobile: boolean;
  toggleInfobar: () => void;
  content: InfobarContent | null;
  setContent: (content: InfobarContent | null) => void;
  isPathnameChanging: boolean;
};

const InfobarContext = React.createContext<InfobarContextProps | null>(null);

export function useInfobar() {
  const context = React.useContext(InfobarContext);
  if (!context) {
    throw new Error('useInfobar must be used within a InfobarProvider.');
  }

  return context;
}

export function InfobarProvider({
  defaultOpen = true,
  open: openProp,
  onOpenChange: setOpenProp,
  className,
  style,
  children,
  ...props
}: React.ComponentProps<'div'> & {
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const isMobile = useIsMobile();
  const [openMobile, setOpenMobile] = React.useState(false);
  const [content, setContent] = React.useState<InfobarContent | null>(null);
  const [contentPathname, setContentPathname] = React.useState<string | null>(null);
  const [isPathnameChanging, setIsPathnameChanging] = React.useState(false);
  const pathname = usePathname();

  // This is the internal state of the infobar.
  // We use openProp and setOpenProp for control from outside the component.
  const [_open, _setOpen] = React.useState(defaultOpen);
  const open = openProp ?? _open;
  const setOpen = React.useCallback(
    (value: boolean | ((value: boolean) => boolean)) => {
      const openState = typeof value === 'function' ? value(open) : value;

      // On mobile, also update the mobile state for the Sheet component
      if (isMobile) {
        setOpenMobile(openState);
      }

      // Handle desktop state
      if (setOpenProp) {
        setOpenProp(openState);
      } else {
        _setOpen(openState);
      }
    },
    [setOpenProp, open, isMobile]
  );

  // Helper to toggle the infobar.
  const toggleInfobar = React.useCallback(() => {
    setOpen((open) => !open);
  }, [setOpen]);

  // Preserve the current infobar state when switching between mobile and desktop.
  React.useEffect(() => {
    if (isMobile) {
      setOpenMobile(open);
    } else {
      setOpen(openMobile);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only reconcile when the breakpoint changes
  }, [isMobile]);

  // Adds a keyboard shortcut to toggle the infobar.
  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === INFOBAR_KEYBOARD_SHORTCUT && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        toggleInfobar();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggleInfobar]);

  // Clear content and close infobar when pathname changes
  React.useEffect(() => {
    if (contentPathname !== null && contentPathname !== pathname) {
      setIsPathnameChanging(true);
      setContent(null);
      setContentPathname(null);
      setOpen(false);

      const timer = setTimeout(() => {
        setIsPathnameChanging(false);
      }, 200);

      return () => clearTimeout(timer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setOpen is a stable React state setter
  }, [pathname, contentPathname]);

  // Update setContent to also track pathname
  const handleSetContent = React.useCallback(
    (newContent: InfobarContent | null) => {
      setContent(newContent);
      setContentPathname(newContent ? pathname : null);
    },
    [pathname]
  );

  // We add a state so that we can do data-state="expanded" or "collapsed".
  // This makes it easier to style the infobar with Tailwind classes.
  const state = open ? 'expanded' : 'collapsed';

  // Update context to use handleSetContent instead of setContent
  const contextValue = React.useMemo<InfobarContextProps>(
    () => ({
      state,
      open,
      setOpen,
      isMobile,
      openMobile,
      setOpenMobile,
      toggleInfobar,
      content,
      setContent: handleSetContent,
      isPathnameChanging
    }),
    [
      state,
      open,
      setOpen,
      isMobile,
      openMobile,
      setOpenMobile,
      toggleInfobar,
      content,
      handleSetContent,
      isPathnameChanging
    ]
  );

  return (
    <InfobarContext.Provider value={contextValue}>
      <TooltipProvider delay={0}>
        <div
          data-slot='infobar-wrapper'
          style={
            {
              '--infobar-width': INFOBAR_WIDTH,
              '--infobar-width-icon': INFOBAR_WIDTH_ICON,
              ...style
            } as React.CSSProperties
          }
          className={cn('group/infobar-wrapper flex flex-1 w-full', className)}
          {...props}
        >
          {children}
        </div>
      </TooltipProvider>
    </InfobarContext.Provider>
  );
}

export function Infobar({
  side = 'left',
  variant = 'sidebar',
  collapsible = 'offcanvas',
  className,
  children,
  ...props
}: React.ComponentProps<'div'> & {
  side?: 'left' | 'right';
  variant?: 'sidebar' | 'floating' | 'inset';
  collapsible?: 'offcanvas' | 'icon' | 'none';
}) {
  const { isMobile, state, setOpen, openMobile, setOpenMobile, isPathnameChanging } = useInfobar();

  if (collapsible === 'none') {
    return (
      <div
        data-slot='infobar'
        className={cn(
          'bg-sidebar text-sidebar-foreground flex h-full w-(--infobar-width) flex-col',
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }

  if (isMobile) {
    return (
      <Sheet
        open={openMobile}
        onOpenChange={(value) => {
          setOpenMobile(value);
          setOpen(value);
        }}
        {...props}
      >
        <SheetContent
          data-infobar='infobar'
          data-slot='infobar'
          data-mobile='true'
          className='bg-sidebar text-sidebar-foreground w-(--infobar-width) p-0 [&>button]:hidden'
          style={
            {
              '--infobar-width': INFOBAR_WIDTH_MOBILE
            } as React.CSSProperties
          }
          side={side}
        >
          <SheetHeader className='sr-only'>
            <SheetTitle>Infobar</SheetTitle>
            <SheetDescription>Displays the mobile infobar.</SheetDescription>
          </SheetHeader>
          <div className='flex h-full w-full flex-col'>{children}</div>
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <div
      className='group peer text-sidebar-foreground relative hidden md:block'
      data-state={state}
      data-collapsible={state === 'collapsed' ? collapsible : ''}
      data-variant={variant}
      data-side={side}
      data-slot='infobar'
      style={
        {
          '--infobar-transition-duration': isPathnameChanging ? '0ms' : '300ms'
        } as React.CSSProperties
      }
    >
      <div
        data-slot='infobar-container'
        className={cn(
          'sticky top-0 z-30 hidden h-[calc(100dvh-3.5rem)] w-(--infobar-width) shrink-0 overflow-hidden rounded-tl-xl border-l border-t transition-[width,opacity] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] md:flex',
          'group-data-[collapsible=offcanvas]:w-0 group-data-[collapsible=offcanvas]:overflow-hidden group-data-[collapsible=offcanvas]:border-0 group-data-[collapsible=offcanvas]:opacity-0',
          className
        )}
        {...props}
      >
        <div
          data-infobar='infobar'
          data-slot='infobar-inner'
          className='bg-sidebar text-sidebar-foreground flex h-full w-full flex-col overflow-y-auto'
        >
          {children}
        </div>
      </div>
    </div>
  );
}
