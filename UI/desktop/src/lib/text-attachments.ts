export const MAX_ATTACHMENT_COUNT = 4;
export const MAX_ATTACHMENT_BYTES = 65_536;
export const MAX_ATTACHMENT_TOTAL_BYTES = 131_072;

const MEDIA_TYPES: Record<string, string> = {
  ".css": "text/css",
  ".csv": "text/csv",
  ".html": "text/html",
  ".ini": "text/plain",
  ".js": "text/javascript",
  ".json": "application/json",
  ".log": "text/plain",
  ".md": "text/markdown",
  ".py": "text/plain",
  ".toml": "text/plain",
  ".ts": "text/plain",
  ".tsx": "text/plain",
  ".txt": "text/plain",
  ".xml": "application/xml",
  ".yaml": "application/yaml",
  ".yml": "application/yaml",
};

export interface TextAttachmentPayload {
  file_name: string;
  media_type: string;
  content_base64: string;
}

export interface PendingTextAttachment extends TextAttachmentPayload {
  key: string;
  size_bytes: number;
}

export async function readTextAttachmentFiles(
  files: FileList | File[],
  existing: PendingTextAttachment[] = [],
): Promise<PendingTextAttachment[]> {
  const selected = Array.from(files);
  if (existing.length + selected.length > MAX_ATTACHMENT_COUNT) {
    throw new Error(`最多可附加 ${MAX_ATTACHMENT_COUNT} 个文本文件`);
  }
  const next: PendingTextAttachment[] = [];
  let totalBytes = existing.reduce((total, item) => total + item.size_bytes, 0);
  for (const file of selected) {
    const mediaType = mediaTypeForFile(file);
    if (file.size <= 0 || file.size > MAX_ATTACHMENT_BYTES) {
      throw new Error(`${file.name} 必须是 1 到 ${MAX_ATTACHMENT_BYTES / 1024} KiB`);
    }
    totalBytes += file.size;
    if (totalBytes > MAX_ATTACHMENT_TOTAL_BYTES) {
      throw new Error(`附件总大小不能超过 ${MAX_ATTACHMENT_TOTAL_BYTES / 1024} KiB`);
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    let text: string;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      throw new Error(`${file.name} 不是有效的 UTF-8 文本`);
    }
    if (!text.trim()) throw new Error(`${file.name} 不能为空`);
    next.push({
      key: `${file.name}:${file.size}:${file.lastModified}`,
      file_name: file.name,
      media_type: mediaType,
      content_base64: bytesToBase64(bytes),
      size_bytes: file.size,
    });
  }
  return [...existing, ...next];
}

export function attachmentPayloads(
  attachments: PendingTextAttachment[],
): TextAttachmentPayload[] {
  return attachments.map(({ file_name, media_type, content_base64 }) => ({
    file_name,
    media_type,
    content_base64,
  }));
}

function mediaTypeForFile(file: File): string {
  const dot = file.name.lastIndexOf(".");
  const extension = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  const expected = MEDIA_TYPES[extension];
  if (!expected) throw new Error(`${file.name} 不是支持的文本文件类型`);
  return expected;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return globalThis.btoa(binary);
}
