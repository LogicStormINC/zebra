import { CheckCircleOutlined, FileTextOutlined, FolderOpenOutlined } from "@ant-design/icons";
import { Tag } from "antd";
import { createStyles } from "antd-style";
import { useEffect, useState } from "react";
import {
  extractChangedFiles,
  summarizeArtifacts,
  summarizeDeliveryAudit,
  type SessionResultFocus,
  type SessionResultSurface,
} from "../lib/session-results";
import locale from "../_utils/local";
import type { SessionArtifactDetailResponse } from "../types";
import { SessionResultDetailPanel } from "./SessionResultDetailPanel";

const useStyle = createStyles(({ css }) => {
  return {
    shell: css`
      margin: 0 0 var(--zebra-space-xl);
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(var(--zebra-grid-wide), 1fr));
      gap: var(--zebra-space-sm);
    `,
    card: css`
      min-width: 0;
      border-radius: var(--zebra-radius-large);
      padding: var(--zebra-space-md);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.045), rgba(255, 255, 255, 0.025));
      border: 1px solid rgba(255, 255, 255, 0.07);
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-sm);
    `,
    header: css`
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--zebra-space-sm);
    `,
    title: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-sm);
      color: rgba(255, 255, 255, 0.92);
      font-size: var(--zebra-font-size-sm);
      font-weight: var(--zebra-font-weight-semibold);
    `,
    icon: css`
      color: rgba(255, 255, 255, 0.6);
    `,
    list: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
    `,
    row: css`
      min-width: 0;
      padding: var(--zebra-space-sm) var(--zebra-space-md);
      border-radius: var(--zebra-radius-soft);
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.04);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--zebra-space-sm);
      min-height: calc(var(--zebra-space-lg) * 2);
      cursor: pointer;
      transition:
        border-color 0.2s ease,
        background 0.2s ease,
        transform 0.2s ease;
      &:hover {
        background: rgba(255, 255, 255, 0.06);
        border-color: rgba(255, 255, 255, 0.1);
        transform: translateY(calc(-1 * var(--zebra-line-indent-step)));
      }
    `,
    rowActive: css`
      background: rgba(242, 140, 56, 0.1);
      border-color: rgba(242, 140, 56, 0.28);
    `,
    rowMain: css`
      min-width: 0;
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      color: rgba(255, 255, 255, 0.86);
      font-size: var(--zebra-font-size-xs);
    `,
    rowText: css`
      min-width: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    `,
    subtle: css`
      color: rgba(255, 255, 255, 0.5);
      font-size: var(--zebra-font-size-2xs);
    `,
    statusPill: css`
      padding: var(--zebra-space-xs);
      border-radius: var(--zebra-radius-pill);
      background: rgba(255, 255, 255, 0.06);
      color: rgba(255, 255, 255, 0.68);
      font-size: var(--zebra-font-size-2xs);
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      flex: 0 0 auto;
    `,
  };
});

function EmptyRow({ text }: { text: string }) {
  const { styles } = useStyle();
  return <div className={styles.subtle}>{text}</div>;
}

export function SessionResultWorkbench({
  artifactContentPreview,
  artifactDetail,
  onSelectArtifact,
  surface,
}: {
  artifactContentPreview: string | null;
  artifactDetail: SessionArtifactDetailResponse | null;
  onSelectArtifact: (artifactId: string) => void;
  surface: SessionResultSurface | null;
}) {
  const { styles } = useStyle();
  const [focus, setFocus] = useState<SessionResultFocus | null>(null);
  const files = extractChangedFiles(surface?.diff ?? null);
  const artifacts = summarizeArtifacts(surface?.artifacts ?? null);
  const audit = summarizeDeliveryAudit(surface?.deliveryAudit ?? null);

  useEffect(() => {
    if (!surface) {
      setFocus(null);
      return;
    }
    if (focus?.kind === "file" && files.some((item) => item.path === focus.path)) {
      return;
    }
    if (focus?.kind === "artifact" && artifacts.some((item) => item.artifact_id === focus.artifactId)) {
      return;
    }
    if (focus?.kind === "delivery" && audit[focus.index]) {
      return;
    }
    if (artifacts.length > 0) {
      setFocus({ kind: "artifact", artifactId: artifacts[0].artifact_id });
      return;
    }
    if (files.length > 0) {
      setFocus({ kind: "file", path: files[0].path });
      return;
    }
    if (audit.length > 0) {
      setFocus({ kind: "delivery", index: 0 });
      return;
    }
    setFocus(null);
  }, [artifacts, audit, files, focus, surface]);

  if (!surface) {
    return null;
  }

  if (files.length === 0 && artifacts.length === 0 && audit.length === 0) {
    return null;
  }

  return (
    <>
      <section className={styles.shell}>
        <div className={styles.card}>
          <div className={styles.header}>
            <div className={styles.title}>
              <FolderOpenOutlined className={styles.icon} />
              <span>{locale.workspaceChanges}</span>
            </div>
            <Tag color={surface.diff?.clean ? "green" : "orange"}>{surface.diff?.clean ? "clean" : "dirty"}</Tag>
          </div>
          <div className={styles.list}>
            {files.length === 0 ? (
              <EmptyRow text={locale.noWorkspaceChanges} />
            ) : (
              files.map((item) => (
                <div
                  className={`${styles.row} ${focus?.kind === "file" && focus.path === item.path ? styles.rowActive : ""}`}
                  key={`${item.status}-${item.path}`}
                  onClick={() => {
                    setFocus({ kind: "file", path: item.path });
                  }}
                >
                  <div className={styles.rowMain}>
                    <span className={styles.statusPill}>{item.status}</span>
                    <span className={styles.rowText}>{item.path}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.header}>
            <div className={styles.title}>
              <FileTextOutlined className={styles.icon} />
              <span>{locale.generatedArtifacts}</span>
            </div>
            <Tag color="blue">{artifacts.length}</Tag>
          </div>
          <div className={styles.list}>
            {artifacts.length === 0 ? (
              <EmptyRow text={locale.noArtifactsYet} />
            ) : (
              artifacts.map((item) => (
                <div
                  className={`${styles.row} ${
                    focus?.kind === "artifact" && focus.artifactId === item.artifact_id ? styles.rowActive : ""
                  }`}
                  key={item.artifact_id}
                  onClick={() => {
                    setFocus({ kind: "artifact", artifactId: item.artifact_id });
                    onSelectArtifact(item.artifact_id);
                  }}
                >
                  <div className={styles.rowMain}>
                    <span className={styles.rowText}>{item.label}</span>
                  </div>
                  <span className={styles.subtle}>{item.kind}</span>
                </div>
              ))
            )}
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.header}>
            <div className={styles.title}>
              <CheckCircleOutlined className={styles.icon} />
              <span>{locale.deliveryRecords}</span>
            </div>
            <Tag color="purple">{audit.length}</Tag>
          </div>
          <div className={styles.list}>
            {audit.length === 0 ? (
              <EmptyRow text={locale.noDeliveryRecords} />
            ) : (
              audit.map((item, index) => (
                <div
                  className={`${styles.row} ${
                    focus?.kind === "delivery" && focus.index === index ? styles.rowActive : ""
                  }`}
                  key={`${item.action}-${item.created_at}-${index}`}
                  onClick={() => {
                    setFocus({ kind: "delivery", index });
                  }}
                >
                  <div className={styles.rowMain}>
                    <span className={styles.rowText}>
                      {item.action} · {item.status}
                    </span>
                  </div>
                  <span className={styles.subtle}>{item.status_code}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
      {focus ? (
        <SessionResultDetailPanel
          artifactContentPreview={artifactContentPreview}
          artifactDetail={artifactDetail}
          focus={focus}
          onOpenArtifact={onSelectArtifact}
          surface={surface}
        />
      ) : null}
    </>
  );
}
