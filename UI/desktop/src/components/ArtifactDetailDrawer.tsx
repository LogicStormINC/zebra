import { Drawer, Space, Spin, Tag, Typography } from "antd";
import { createStyles } from "antd-style";
import type { ArtifactSummary, SessionArtifactDetailResponse } from "../types";

const useStyle = createStyles(({ css }) => {
  return {
    drawer: css`
      width: min(92vw, 560px);
      .ant-drawer-title {
        font-size: var(--zebra-font-size-md);
        font-weight: var(--zebra-font-weight-semibold);
      }
      .ant-drawer-body {
        padding: var(--zebra-space-lg);
        display: flex;
        flex-direction: column;
        gap: var(--zebra-space-sm);
      }
      .ant-drawer-body > .ant-space {
        width: 100%;
      }
      .ant-drawer-body pre {
        margin: 0;
        white-space: pre-wrap;
        overflow-x: auto;
        padding: var(--zebra-space-sm);
        border-radius: var(--zebra-radius-soft);
        border: 1px solid rgba(255, 255, 255, 0.05);
        background: rgba(255, 255, 255, 0.05);
        font-size: var(--zebra-font-size-2xs);
        font-family: var(--zebra-font-family-code);
        line-height: var(--zebra-line-height-relaxed);
      }
      .ant-drawer-body pre + pre {
        margin-top: var(--zebra-space-sm);
      }
      @media (min-width: 1280px) {
        width: 620px;
      }
    `,
    metaSpace: css`
      width: 100%;
    `,
    blockTitle: css`
      color: rgba(255, 255, 255, 0.86);
      font-size: var(--zebra-font-size-sm);
      font-weight: var(--zebra-font-weight-semibold);
      margin-bottom: var(--zebra-space-2xs);
    `,
    bodyText: css`
      color: rgba(255, 255, 255, 0.84);
      font-size: var(--zebra-font-size-sm);
      line-height: var(--zebra-line-height-relaxed);
    `,
    metaLabel: css`
      color: rgba(255, 255, 255, 0.6);
      font-size: var(--zebra-font-size-2xs);
      text-transform: uppercase;
      letter-spacing: 0.07em;
    `,
  };
});

interface ArtifactDetailDrawerProps {
  contentPreview: string | null;
  detail: SessionArtifactDetailResponse | null;
  loading: boolean;
  onClose: () => void;
  open: boolean;
}

function DetailBody({
  contentPreview,
  detail,
  bodySpaceClassName,
  styles,
}: {
  contentPreview: string | null;
  detail: SessionArtifactDetailResponse | null;
  bodySpaceClassName: string;
  styles: {
    blockTitle: string;
    bodyText: string;
    metaLabel: string;
  };
}) {
  if (!detail) {
    return <Typography.Text type="secondary">No artifact selected.</Typography.Text>;
  }

  const artifact: ArtifactSummary = detail.artifact;
  return (
    <Space direction="vertical" size="middle" className={bodySpaceClassName}>
      <Space wrap>
        <Tag color="blue">{artifact.source}</Tag>
        <Tag>{artifact.kind}</Tag>
        <Tag color={artifact.access.allowed ? "green" : "red"}>{artifact.access.class}</Tag>
        <Tag color="purple">{artifact.retrieval.status}</Tag>
      </Space>
      <Typography.Text className={styles.blockTitle}>{artifact.label}</Typography.Text>
      <Typography.Text className={styles.bodyText} type="secondary">
        {artifact.preview ?? "(no preview)"}
      </Typography.Text>
      <Typography.Text className={styles.blockTitle}>Metadata</Typography.Text>
      <span className={styles.metaLabel}>Artifact Metadata</span>
      <pre>{JSON.stringify(artifact.metadata, null, 2)}</pre>
      {contentPreview ? (
        <>
          <Typography.Text className={styles.blockTitle}>Content</Typography.Text>
          <pre>{contentPreview}</pre>
        </>
      ) : null}
    </Space>
  );
}

export function ArtifactDetailDrawer({
  contentPreview,
  detail,
  loading,
  onClose,
  open,
}: ArtifactDetailDrawerProps) {
  const { styles } = useStyle();

  return (
    <Drawer
      destroyOnClose={false}
      onClose={onClose}
      className={styles.drawer}
      open={open}
      placement="right"
      title="Artifact detail"
    >
      {loading ? <Spin /> : <DetailBody contentPreview={contentPreview} detail={detail} bodySpaceClassName={styles.metaSpace} styles={styles} />}
    </Drawer>
  );
}
