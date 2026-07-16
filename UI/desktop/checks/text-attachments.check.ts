import assert from "node:assert/strict";
import {
  attachmentPayloads,
  DOCX_MEDIA_TYPE,
  XLSX_MEDIA_TYPE,
  PPTX_MEDIA_TYPE,
  MAX_ATTACHMENT_COUNT,
  readAttachmentFiles,
} from "../src/lib/text-attachments.ts";

const file = new File(["ATTACHMENT-CHECK-131"], "brief.md", {
  type: "text/markdown",
  lastModified: 131,
});
const attachments = await readAttachmentFiles([file]);
assert.equal(attachments[0].file_name, "brief.md");
assert.equal(attachments[0].media_type, "text/markdown");
assert.equal(attachmentPayloads(attachments)[0].content_base64, "QVRUQUNITUVOVC1DSEVDSy0xMzE=");

await assert.rejects(
  readAttachmentFiles(Array.from({ length: MAX_ATTACHMENT_COUNT + 1 }, () => file)),
  /最多可附加/,
);

const xlsx = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x02])], "brief.xlsx", {
  type: XLSX_MEDIA_TYPE,
  lastModified: 142,
});
const xlsxAttachments = await readAttachmentFiles([xlsx]);
assert.equal(xlsxAttachments[0].media_type, XLSX_MEDIA_TYPE);
const pptx = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x03])], "brief.pptx", {
  type: PPTX_MEDIA_TYPE,
  lastModified: 143,
});
const pptxAttachments = await readAttachmentFiles([pptx]);
assert.equal(pptxAttachments[0].media_type, PPTX_MEDIA_TYPE);
await assert.rejects(
  readAttachmentFiles([new File(["x"], "image.png")]),
  /不是支持的附件类型/,
);

const pdf = new File(["%PDF-1.7\nfixture"], "brief.pdf", {
  type: "application/pdf",
  lastModified: 140,
});
const pdfAttachments = await readAttachmentFiles([pdf]);
assert.equal(pdfAttachments[0].media_type, "application/pdf");
assert.equal(attachmentPayloads(pdfAttachments)[0].content_base64, "JVBERi0xLjcKZml4dHVyZQ==");

const docx = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x01])], "brief.docx", {
  type: DOCX_MEDIA_TYPE,
  lastModified: 141,
});
const docxAttachments = await readAttachmentFiles([docx]);
assert.equal(docxAttachments[0].media_type, DOCX_MEDIA_TYPE);
assert.equal(attachmentPayloads(docxAttachments)[0].content_base64, "UEsDBAE=");

await assert.rejects(
  readAttachmentFiles([new File(["not-docx"], "brief.docx")]),
  /不是有效的 DOCX/,
);
await assert.rejects(
  readAttachmentFiles([new File(["not-pptx"], "brief.pptx")]),
  /不是有效的 PPTX/,
);
