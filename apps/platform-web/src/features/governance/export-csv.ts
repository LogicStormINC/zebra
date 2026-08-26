/**
 * 前端 CSV 导出（PRD 22.3 / 23.3）：
 * 生成带表头的 CSV 字符串，经 Blob + URL.createObjectURL 触发下载。
 * 导出动作本身需要写入 Audit Log（由调用方 toast 提示）。
 */

export function csvEscape(value: string | number | undefined | null): string {
  const text = String(value ?? '');
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** 简单确定性校验摘要（FNV-1a 32bit，hex）：用于导出文件尾部的完整性校验行。 */
export function csvChecksum(rows: (string | number)[][]): string {
  const body = rows.map((row) => row.map(csvEscape).join(',')).join('\n');
  let hash = 0x811c9dc5;
  for (let i = 0; i < body.length; i += 1) {
    hash ^= body.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `fnv1a32:${hash.toString(16).padStart(8, '0')}`;
}

export function downloadCsv(filename: string, rows: (string | number)[][], withChecksum = false) {
  const lines = rows.map((row) => row.map(csvEscape).join(','));
  if (withChecksum) {
    lines.push(`# checksum,${csvChecksum(rows)}`);
  }
  // BOM 保证 Excel 以 UTF-8 打开中文
  const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
