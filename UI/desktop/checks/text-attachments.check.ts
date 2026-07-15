import assert from "node:assert/strict";
import {
  attachmentPayloads,
  MAX_ATTACHMENT_COUNT,
  readTextAttachmentFiles,
} from "../src/lib/text-attachments.ts";

const file = new File(["ATTACHMENT-CHECK-131"], "brief.md", {
  type: "text/markdown",
  lastModified: 131,
});
const attachments = await readTextAttachmentFiles([file]);
assert.equal(attachments[0].file_name, "brief.md");
assert.equal(attachments[0].media_type, "text/markdown");
assert.equal(attachmentPayloads(attachments)[0].content_base64, "QVRUQUNITUVOVC1DSEVDSy0xMzE=");

await assert.rejects(
  readTextAttachmentFiles(Array.from({ length: MAX_ATTACHMENT_COUNT + 1 }, () => file)),
  /最多可附加/,
);
await assert.rejects(
  readTextAttachmentFiles([new File(["x"], "image.png")]),
  /不是支持的文本文件类型/,
);
