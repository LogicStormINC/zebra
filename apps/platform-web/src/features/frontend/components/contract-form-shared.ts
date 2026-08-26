/**
 * Frontend Profile 契约表单共享工具（PRD 35.4.1）：
 * 列表 / 数字解析与 Draft 保存提示文案。
 */

export const DRAFT_TOAST_DESCRIPTION =
  'Contract 变更已保存到 Draft，将随 Profile 新 Revision 发布并生成新 Digest（历史 Revision 不可变）';

/** 逗号 / 空白分隔的列表输入 → string[]。 */
export function parseList(raw: string): string[] {
  return raw
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function parsePositiveInt(raw: string, fallback: number): number {
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
