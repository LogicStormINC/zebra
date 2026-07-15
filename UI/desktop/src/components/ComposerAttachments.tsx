import { FileTextOutlined, PaperClipOutlined } from "@ant-design/icons";
import React from "react";
import {
  readTextAttachmentFiles,
  type PendingTextAttachment,
} from "../lib/text-attachments";
import { useComposerAttachmentsStyle } from "./ComposerAttachments.styles";

interface ComposerAttachmentsProps {
  attachments: PendingTextAttachment[];
  disabled: boolean;
  onChange: (attachments: PendingTextAttachment[]) => void;
}

export function ComposerAttachments({
  attachments,
  disabled,
  onChange,
}: ComposerAttachmentsProps) {
  const { styles } = useComposerAttachmentsStyle();
  const [error, setError] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  return (
    <div className={styles.surface} aria-label="文本附件">
      <input
        accept=".txt,.md,.csv,.json,.yaml,.yml,.xml,.html,.css,.js,.ts,.tsx,.py,.toml,.ini,.log"
        className={styles.fileInput}
        multiple
        onChange={(event) => {
          const files = event.currentTarget.files;
          if (files?.length) {
            void readTextAttachmentFiles(files, attachments)
              .then((next) => {
                onChange(next);
                setError("");
              })
              .catch((reason: unknown) => {
                setError(reason instanceof Error ? reason.message : "附件读取失败");
              });
          }
          event.currentTarget.value = "";
        }}
        ref={inputRef}
        type="file"
      />
      <button
        aria-label="附加文本文件"
        className={styles.attachButton}
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        type="button"
      ><PaperClipOutlined /></button>
      {attachments.map((attachment) => (
        <span className={styles.chip} key={attachment.key}>
          <FileTextOutlined />
          <span>{attachment.file_name}</span>
          <small>{Math.ceil(attachment.size_bytes / 1024)} KiB</small>
          <button
            aria-label={`移除 ${attachment.file_name}`}
            onClick={() => onChange(attachments.filter((item) => item.key !== attachment.key))}
            type="button"
          >×</button>
        </span>
      ))}
      {error ? <span className={styles.error} role="alert">{error}</span> : null}
    </div>
  );
}
