'use client';
import { useCallback, useSyncExternalStore } from 'react';
import type { AgUiViewStore } from '@zebra-agent/client-core';

/** Unmount/switch only removes observation subscriptions; never cancels execution. */
export function useAgUiView(store: AgUiViewStore) { return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot); }
export function useAgUiFacts(store: AgUiViewStore) { return useSyncExternalStore(store.subscribeFacts, store.getFacts, store.getFacts); }
export function useAgUiEntity(store: AgUiViewStore, id: string) {
  const subscribe = useCallback((listener: () => void) => store.subscribeEntity(id, listener), [store, id]);
  const snapshot = useCallback(() => store.getEntity(id), [store, id]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
export function useAgUiInterrupts(store: AgUiViewStore) { return useSyncExternalStore(store.subscribeInterrupts, store.getInterrupts, store.getInterrupts); }
