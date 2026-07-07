import { Button, Tag } from "antd";
import { createStyles } from "antd-style";
import type { SessionArtifactDetailResponse } from "../types";
import {
  extractDiffChunk,
  extractChangedFiles,
  summarizeArtifacts,
  summarizeDeliveryAudit,
  type SessionResultFocus,
  type SessionResultSurface,
} from "../lib/session-results";

const useStyle = createStyles(({ css }) => {
  return {
    panel: css`
      margin: 0 0 var(--zebra-space-xl);
      border-radius: var(--zebra-radius-large);
      padding: var(--zebra-space-md) var(--zebra-space-lg) calc(var(--zebra-space-lg) + var(--zebra-space-3xs));
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.025));
      border: 1px solid rgba(255, 255, 255, 0.08);
      box-shadow: var(--zebra-shadow-md);
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-sm);
    `,
    header: css`
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--zebra-space-sm);
      flex-wrap: wrap;
    `,
    titleBlock: css`
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
      strong {
        font-size: var(--zebra-font-size-md);
        color: rgba(255, 255, 255, 0.94);
      }
      span {
        color: rgba(255, 255, 255, 0.52);
        font-size: var(--zebra-font-size-xs);
      }
    `,
    body: css`
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(var(--zebra-grid-detail), 0.9fr);
      gap: var(--zebra-space-sm);
      @media (max-width: 1019px) {
        grid-template-columns: 1fr;
      }
    `,
    console: css`
      min-width: 0;
      margin: 0;
      padding: var(--zebra-space-md);
      border-radius: var(--zebra-radius-card);
      background: #101010;
      border: 1px solid rgba(255, 255, 255, 0.06);
      color: rgba(255, 255, 255, 0.84);
      font-size: var(--zebra-font-size-2xs);
      line-height: var(--zebra-line-height-relaxed);
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
    `,
    rail: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-sm);
    `,
    card: css`
      padding: var(--zebra-space-sm) var(--zebra-space-md);
      border-radius: var(--zebra-radius-card);
      background: rgba(255, 255, 255, 0.035);
      border: 1px solid rgba(255, 255, 255, 0.05);
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
    `,
    metaLabel: css`
      color: rgba(255, 255, 255, 0.46);
      font-size: var(--zebra-font-size-2xs);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    `,
    metaValue: css`
      color: rgba(255, 255, 255, 0.88);
      font-size: var(--zebra-font-size-sm);
      line-height: var(--zebra-line-height-relaxed);
      word-break: break-word;
    `,
    metaRow: css`
      display: flex;
      flex-wrap: wrap;
      gap: var(--zebra-space-xs);
    `,
    actionButton: css`
      background: rgba(255, 255, 255, 0.04);
      border-color: rgba(255, 255, 255, 0.09);
      color: rgba(255, 255, 255, 0.84);
      &:hover {
        color: white !important;
        border-color: rgba(255, 255, 255, 0.18) !important;
        background: rgba(255, 255, 255, 0.08) !important;
      }
    `,
  };
});

function stringifyMetadata(value: unknown) {
  if (value === null || value === undefined) {
    return "(empty)";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function matchedArtifactDetail(
  focus: SessionResultFocus,
  artifactDetail: SessionArtifactDetailResponse | null,
) {
  if (focus.kind !== "artifact") {
    return null;
  }
  if (!artifactDetail || artifactDetail.artifact.artifact_id !== focus.artifactId) {
    return null;
  }
  return artifactDetail;
}

interface SessionResultDetailPanelProps {
  artifactContentPreview: string | null;
  artifactDetail: SessionArtifactDetailResponse | null;
  focus: SessionResultFocus;
  onOpenArtifact: (artifactId: string) => void;
  surface: SessionResultSurface;
}

export function SessionResultDetailPanel({
  artifactContentPreview,
  artifactDetail,
  focus,
  onOpenArtifact,
  surface,
}: SessionResultDetailPanelProps) {
  const { styles } = useStyle();
  const files = extractChangedFiles(surface.diff);
  const artifacts = summarizeArtifacts(surface.artifacts);
  const audit = summarizeDeliveryAudit(surface.deliveryAudit);

  if (focus.kind === "file") {
    const selected = files.find((item) => item.path === focus.path) ?? files[0];
    const patch = extractDiffChunk(surface.diff, selected?.path ?? "");
    return (
      <section className={styles.panel}>
        <div className={styles.header}>
          <div className={styles.titleBlock}>
            <strong>{selected?.path ?? "Workspace diff"}</strong>
            <span>{surface.diff?.workspace ?? "Workspace unavailable"}</span>
          </div>
          <Tag color={surface.diff?.clean ? "green" : "orange"}>{selected?.status ?? "M"}</Tag>
        </div>
        <div className={styles.body}>
          <pre className={styles.console}>{patch || surface.diff?.git_status || "(empty)"}</pre>
          <div className={styles.rail}>
            <div className={styles.card}>
              <span className={styles.metaLabel}>Git Status</span>
              <pre className={styles.console}>{surface.diff?.git_status || "(empty)"}</pre>
            </div>
            <div className={styles.card}>
              <span className={styles.metaLabel}>Selection</span>
              <span className={styles.metaValue}>{selected?.path ?? "(none)"}</span>
            </div>
          </div>
        </div>
      </section>
    );
  }

  if (focus.kind === "artifact") {
    const artifact = artifacts.find((item) => item.artifact_id === focus.artifactId) ?? artifacts[0];
    if (!artifact) {
      return null;
    }
    const detail = matchedArtifactDetail(focus, artifactDetail);
    const preview = detail ? artifactContentPreview ?? detail.artifact.preview : artifact.preview;
    return (
      <section className={styles.panel}>
        <div className={styles.header}>
          <div className={styles.titleBlock}>
            <strong>{artifact.label}</strong>
            <span>{artifact.artifact_id}</span>
          </div>
          <div className={styles.metaRow}>
            <Tag color="blue">{artifact.kind}</Tag>
            <Tag color={artifact.retrieval.retrievable ? "green" : "default"}>
              {artifact.retrieval.retrievable ? "retrievable" : artifact.retrieval.status}
            </Tag>
            <Button className={styles.actionButton} onClick={() => onOpenArtifact(artifact.artifact_id)} size="small">
              打开详情
            </Button>
          </div>
        </div>
        <div className={styles.body}>
          <pre className={styles.console}>{preview || "(no preview available)"}</pre>
          <div className={styles.rail}>
            <div className={styles.card}>
              <span className={styles.metaLabel}>Source</span>
              <span className={styles.metaValue}>{artifact.source}</span>
            </div>
            <div className={styles.card}>
              <span className={styles.metaLabel}>Access</span>
              <span className={styles.metaValue}>
                {artifact.access.class} · {artifact.access.allowed ? "allowed" : "blocked"}
              </span>
            </div>
            <div className={styles.card}>
              <span className={styles.metaLabel}>Metadata</span>
              <pre className={styles.console}>{stringifyMetadata(artifact.metadata)}</pre>
            </div>
          </div>
        </div>
      </section>
    );
  }

  const selectedRecord = audit[focus.index] ?? audit[0];
  if (!selectedRecord) {
    return null;
  }

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <strong>
            {selectedRecord.action} · {selectedRecord.status}
          </strong>
          <span>{selectedRecord.created_at}</span>
        </div>
        <div className={styles.metaRow}>
          <Tag color="purple">{selectedRecord.status_code}</Tag>
          <Tag>{selectedRecord.policy_profile}</Tag>
        </div>
      </div>
      <div className={styles.body}>
        <pre className={styles.console}>{stringifyMetadata(selectedRecord.result_metadata)}</pre>
        <div className={styles.rail}>
          <div className={styles.card}>
            <span className={styles.metaLabel}>Idempotency Key</span>
            <span className={styles.metaValue}>{selectedRecord.idempotency_key ?? "(none)"}</span>
          </div>
          <div className={styles.card}>
            <span className={styles.metaLabel}>Action</span>
            <span className={styles.metaValue}>{selectedRecord.action}</span>
          </div>
          <div className={styles.card}>
            <span className={styles.metaLabel}>Status</span>
            <span className={styles.metaValue}>{selectedRecord.status}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
