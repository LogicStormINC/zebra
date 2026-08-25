'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { type Parser, parseAsArrayOf, parseAsInteger, parseAsString, useQueryStates } from 'nuqs';

import { useDataTable } from '@/hooks/use-data-table';
import { getSortingStateParser } from '@/lib/parsers';

/**
 * mock 数据源下的 TanStack 表格装配（与 products-table 的服务端分页模式对齐）：
 * use-data-table 为 manual 模式，这里以 URL 查询参数为唯一事实来源，
 * 在客户端完成「筛选 → 排序 → 分页」后，把当前页数据交给 useDataTable，
 * 工具栏（DataTableToolbar）与分页（DataTablePagination）行为不变。
 */
export type MockTableSpec<T> = {
  /** 文本筛选列：columnId → 行取值（不区分大小写的包含匹配） */
  textFilters?: Record<string, (row: T) => string>;
  /** 多选筛选列：columnId → 行取值（与选项 value 全等） */
  selectFilters?: Record<string, (row: T) => string>;
  /** 可排序列：columnId → 行取值 */
  sortAccessors?: Record<string, (row: T) => string | number>;
};

export function useMockDataTable<T>({
  rows,
  columns,
  spec = {},
  defaultPageSize = 10
}: {
  rows: T[];
  columns: ColumnDef<T, unknown>[];
  spec?: MockTableSpec<T>;
  defaultPageSize?: number;
}) {
  const columnIds = useMemo(
    () => columns.map((column) => column.id).filter(Boolean) as string[],
    [columns]
  );

  const baseParsers = useMemo(
    () => ({
      page: parseAsInteger.withDefault(1),
      perPage: parseAsInteger.withDefault(defaultPageSize),
      sort: getSortingStateParser<T>(columnIds).withDefault([])
    }),
    [columnIds, defaultPageSize]
  );

  const filterParsers = useMemo(() => {
    const record: Record<string, Parser<string> | Parser<string[]>> = {};
    for (const key of Object.keys(spec.textFilters ?? {})) {
      record[key] = parseAsString;
    }
    for (const key of Object.keys(spec.selectFilters ?? {})) {
      record[key] = parseAsArrayOf(parseAsString, ',');
    }
    return record;
  }, [spec]);

  const [base] = useQueryStates(baseParsers);
  const [filterValues] = useQueryStates(filterParsers);

  const view = useMemo(() => {
    const filtered = rows.filter((row) => {
      const textEntries = Object.entries(spec.textFilters ?? {});
      for (const [key, accessor] of textEntries) {
        const raw = filterValues[key];
        if (typeof raw === 'string' && raw.trim().length > 0) {
          if (!accessor(row).toLowerCase().includes(raw.trim().toLowerCase())) return false;
        }
      }
      const selectEntries = Object.entries(spec.selectFilters ?? {});
      for (const [key, accessor] of selectEntries) {
        const selected = filterValues[key];
        if (Array.isArray(selected) && selected.length > 0 && !selected.includes(accessor(row))) {
          return false;
        }
      }
      return true;
    });

    const sort = base.sort ?? [];
    const sorted = [...filtered];
    for (const item of sort.toReversed()) {
      const accessor = spec.sortAccessors?.[item.id];
      if (!accessor) continue;
      sorted.sort((a, b) => {
        const left = accessor(a);
        const right = accessor(b);
        const compared =
          typeof left === 'number' && typeof right === 'number'
            ? left - right
            : String(left).localeCompare(String(right));
        return item.desc ? -compared : compared;
      });
    }

    const perPage = base.perPage ?? defaultPageSize;
    const page = base.page ?? 1;
    const pageCount = Math.max(1, Math.ceil(sorted.length / perPage));
    const safePage = Math.min(page, pageCount);
    const start = (safePage - 1) * perPage;
    return {
      rows: sorted.slice(start, start + perPage),
      pageCount,
      total: sorted.length
    };
  }, [rows, spec, base, filterValues, defaultPageSize]);

  const { table } = useDataTable({
    data: view.rows,
    columns,
    pageCount: view.pageCount,
    initialState: {
      pagination: { pageIndex: 0, pageSize: defaultPageSize }
    }
  });

  return { table, total: view.total, pageCount: view.pageCount };
}
