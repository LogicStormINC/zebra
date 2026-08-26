'use client';

/**
 * Navigation filtering hook.
 *
 * Zebra Platform Console 当前阶段不引入用户体系，导航不做 RBAC 过滤。
 * 后续接入 Operator Identity 后，可在此处按角色过滤导航项，
 * 服务端仍保留最终授权校验。
 */

import { useMemo } from 'react';
import type { NavGroup, NavItem } from '@/types';

export function useFilteredNavItems(items: NavItem[]) {
  return useMemo(() => items, [items]);
}

export function useFilteredNavGroups(groups: NavGroup[]) {
  return useMemo(() => {
    return groups
      .map((group) => ({ ...group, items: group.items.filter((item) => !!item) }))
      .filter((group) => group.items.length > 0);
  }, [groups]);
}
