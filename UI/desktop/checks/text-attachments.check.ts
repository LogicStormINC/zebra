import assert from "node:assert/strict";
import {
  attachmentPayloads,
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
