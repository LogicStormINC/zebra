export const MAX_ATTACHMENT_COUNT = 4;
export const MAX_ATTACHMENT_BYTES = 65_536;
export const MAX_ATTACHMENT_TOTAL_BYTES = 131_072;
export const MAX_PDF_BYTES = 4_194_304;
export const MAX_DOCX_BYTES = 4_194_304;
export const MAX_XLSX_BYTES = 4_194_304;
export const MAX_DOCUMENT_TOTAL_BYTES = 8_388_608;
export const DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
export const XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

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
  ".docx": DOCX_MEDIA_TYPE,
  ".xlsx": XLSX_MEDIA_TYPE,
};

export interface AttachmentPayload {
  file_name: string;
  media_type: string;
  content_base64: string;
}

export interface PendingAttachment extends AttachmentPayload {
  key: string;
  size_bytes: number;
}

export async function readAttachmentFiles(
  files: FileList | File[],
  existing: PendingAttachment[] = [],
): Promise<PendingAttachment[]> {
  const selected = Array.from(files);
  if (existing.length + selected.length > MAX_ATTACHMENT_COUNT) {
    throw new Error(`最多可附加 ${MAX_ATTACHMENT_COUNT} 个文件`);
  }
  const next: PendingAttachment[] = [];
  let textBytes = existing
    .filter((item) => !isDocumentMediaType(item.media_type))
    .reduce((total, item) => total + item.size_bytes, 0);
  let documentBytes = existing
    .filter((item) => isDocumentMediaType(item.media_type))
    .reduce((total, item) => total + item.size_bytes, 0);
  for (const file of selected) {
    const mediaType = mediaTypeForFile(file);
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (isDocumentMediaType(mediaType)) {
      const maxBytes = mediaType === "application/pdf"
        ? MAX_PDF_BYTES
        : mediaType === DOCX_MEDIA_TYPE ? MAX_DOCX_BYTES : MAX_XLSX_BYTES;
      if (file.size <= 0 || file.size > maxBytes) {
        throw new Error(`${file.name} 必须是 1 到 ${maxBytes / 1024 / 1024} MiB`);
      }
      if (mediaType === "application/pdf" && !startsWithPdfSignature(bytes)) {
        throw new Error(`${file.name} 不是有效的 PDF 文件`);
      }
      if ([DOCX_MEDIA_TYPE, XLSX_MEDIA_TYPE].includes(mediaType) && !startsWithZipSignature(bytes)) {
        throw new Error(`${file.name} 不是有效的 ${mediaType === DOCX_MEDIA_TYPE ? "DOCX" : "XLSX"} 文件`);
      }
      documentBytes += file.size;
      if (documentBytes > MAX_DOCUMENT_TOTAL_BYTES) {
        throw new Error(`文档附件总大小不能超过 ${MAX_DOCUMENT_TOTAL_BYTES / 1024 / 1024} MiB`);
      }
    } else {
      if (file.size <= 0 || file.size > MAX_ATTACHMENT_BYTES) {
        throw new Error(`${file.name} 必须是 1 到 ${MAX_ATTACHMENT_BYTES / 1024} KiB`);
      }
      textBytes += file.size;
      if (textBytes > MAX_ATTACHMENT_TOTAL_BYTES) {
        throw new Error(`文本附件总大小不能超过 ${MAX_ATTACHMENT_TOTAL_BYTES / 1024} KiB`);
      }
      validateUtf8Text(file.name, bytes);
    }
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
  attachments: PendingAttachment[],
): AttachmentPayload[] {
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
  if (extension === ".pdf") return "application/pdf";
  if (!expected) throw new Error(`${file.name} 不是支持的附件类型`);
  return expected;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32_768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32_768));
  }
  return globalThis.btoa(binary);
}

function validateUtf8Text(fileName: string, bytes: Uint8Array): void {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error(`${fileName} 不是有效的 UTF-8 文本`);
  }
  if (!text.trim()) throw new Error(`${fileName} 不能为空`);
}

function startsWithPdfSignature(bytes: Uint8Array): boolean {
  return bytes.length >= 5
    && bytes[0] === 0x25
    && bytes[1] === 0x50
    && bytes[2] === 0x44
    && bytes[3] === 0x46
    && bytes[4] === 0x2d;
}

function startsWithZipSignature(bytes: Uint8Array): boolean {
  return bytes.length >= 4
    && bytes[0] === 0x50
    && bytes[1] === 0x4b
    && bytes[2] === 0x03
    && bytes[3] === 0x04;
}

export function isDocumentMediaType(mediaType: string): boolean {
  return mediaType === "application/pdf"
    || mediaType === DOCX_MEDIA_TYPE
    || mediaType === XLSX_MEDIA_TYPE;
}
