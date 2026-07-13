import { CheckCircleOutlined, ExportOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, Button, Input, Popconfirm, Tag } from "antd";
import { createStyles } from "antd-style";
import { useEffect, useState } from "react";
import { extractChangedFiles, summarizeArtifacts, summarizeDeliveryAudit, type SessionResultSurface } from "../lib/session-results";
import { projectDeliveryAvailability, type PullRequestInput, type SessionDeliveryController } from "../lib/session-delivery";

const useStyle = createStyles(({ css }) => ({
  panel: css`
    margin: 0 0 var(--zebra-space-xl);
    padding: var(--zebra-space-md);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--zebra-radius-large);
    background: rgba(255, 255, 255, 0.025);
    display: flex;
    flex-direction: column;
    gap: var(--zebra-space-md);
  `,
  header: css`
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--zebra-space-sm);
    flex-wrap: wrap;
  `,
  title: css`
    display: flex;
    gap: var(--zebra-space-sm);
    align-items: center;
    color: rgba(255, 255, 255, 0.92);
    font-size: var(--zebra-font-size-sm);
    font-weight: var(--zebra-font-weight-semibold);
  `,
  evidence: css`
    display: flex;
    flex-wrap: wrap;
    gap: var(--zebra-space-xs);
  `,
  grid: css`
    display: grid;
    grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr);
    gap: var(--zebra-space-md);
    @media (max-width: 900px) { grid-template-columns: 1fr; }
  `,
  action: css`
    min-width: 0;
    padding: var(--zebra-space-md);
    border-radius: var(--zebra-radius-card);
    border: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(255, 255, 255, 0.025);
    display: flex;
    flex-direction: column;
    gap: var(--zebra-space-sm);
  `,
  actionTitle: css`
    color: rgba(255, 255, 255, 0.88);
    font-size: var(--zebra-font-size-sm);
    font-weight: var(--zebra-font-weight-semibold);
  `,
  fields: css`
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--zebra-space-sm);
    @media (max-width: 620px) { grid-template-columns: 1fr; }
  `,
  actions: css`
    display: flex;
    gap: var(--zebra-space-sm);
    flex-wrap: wrap;
  `,
  hint: css`
    color: rgba(255, 255, 255, 0.48);
    font-size: var(--zebra-font-size-2xs);
    line-height: var(--zebra-line-height-relaxed);
  `,
}));

interface SessionDeliveryPanelProps {
  controller: SessionDeliveryController;
  sessionId: string | undefined;
  policyProfile: string | undefined;
  sessionStatus: string | undefined;
  surface: SessionResultSurface | null;
}

export function SessionDeliveryPanel({ controller, policyProfile, sessionId, sessionStatus, surface }: SessionDeliveryPanelProps) {
  const { styles } = useStyle();
  const availability = projectDeliveryAvailability(sessionStatus, surface, policyProfile);
  const [commitMessage, setCommitMessage] = useState("Apply Zebra Agent session changes");
  const [pullRequest, setPullRequest] = useState<PullRequestInput>({
    title: "Zebra Agent session changes",
    body: "Generated from the Zebra Agent desktop workspace.",
    base_branch: "main",
  });
  const [planned, setPlanned] = useState<PullRequestInput | null>(null);
  const plan = controller.pullRequestResult?.pull_request;
  useEffect(() => setPlanned(null), [sessionId]);
  const updatePullRequest = (patch: Partial<PullRequestInput>) => {
    setPullRequest((current) => ({ ...current, ...patch }));
    setPlanned(null);
  };
  const planPullRequest = () => {
    void controller.planPullRequest(pullRequest).then(() => setPlanned(pullRequest)).catch(() => undefined);
  };

  return (
    <section aria-label="结果审阅与安全交付" className={styles.panel}>
      <div className={styles.header}>
        <div className={styles.title}><SafetyCertificateOutlined />结果审阅与安全交付</div>
        <div className={styles.evidence}>
          <Tag>{extractChangedFiles(surface?.diff ?? null).length} 个变更文件</Tag>
          <Tag>{summarizeArtifacts(surface?.artifacts ?? null).length} 个验证产物</Tag>
          <Tag>{summarizeDeliveryAudit(surface?.deliveryAudit ?? null).length} 条交付记录</Tag>
        </div>
      </div>
      {controller.errorText ? <Alert showIcon type="error" message="交付操作失败" description={controller.errorText} /> : null}
      {availability.reason ? <Alert showIcon type="info" message={availability.reason} /> : null}
      <div className={styles.grid}>
        <div className={styles.action}>
          <span className={styles.actionTitle}>创建提交</span>
          <span className={styles.hint}>提交前请先在上方核对 Diff、验证产物和未解决风险。</span>
          <Input value={commitMessage} onChange={(event) => setCommitMessage(event.target.value)} placeholder="Commit message" />
          <Button
            disabled={!availability.canCommit || !commitMessage.trim()}
            icon={<CheckCircleOutlined />}
            loading={controller.busy}
            onClick={() => void controller.commit({ message: commitMessage.trim() }).catch(() => undefined)}
            type="primary"
          >创建 Commit</Button>
          {controller.commitResult?.committed ? <Alert showIcon type="success" message={`已创建 ${controller.commitResult.commit_sha?.slice(0, 12)}`} /> : null}
        </div>
        <div className={styles.action}>
          <span className={styles.actionTitle}>Pull Request</span>
          <span className={styles.hint}>先生成无副作用计划；只有计划确认后才能执行创建。</span>
          <Input value={pullRequest.title} onChange={(event) => updatePullRequest({ title: event.target.value })} placeholder="PR title" />
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} value={pullRequest.body} onChange={(event) => updatePullRequest({ body: event.target.value })} placeholder="PR body" />
          <div className={styles.fields}>
            <Input value={pullRequest.base_branch} onChange={(event) => updatePullRequest({ base_branch: event.target.value })} placeholder="Base branch" />
            <Input value={pullRequest.head_branch ?? ""} onChange={(event) => updatePullRequest({ head_branch: event.target.value || undefined })} placeholder="Head branch" />
          </div>
          <div className={styles.actions}>
            <Button disabled={!availability.canPlanPullRequest || !pullRequest.title.trim()} loading={controller.busy} onClick={planPullRequest}>生成 PR 计划</Button>
            <Popconfirm
              disabled={!planned || plan?.provider !== "github"}
              description="将使用刚才审阅的参数执行远端创建。"
              onConfirm={() => planned && void controller.executePullRequest(planned).catch(() => undefined)}
              title="确认创建 Pull Request？"
            >
              <Button disabled={!planned || plan?.provider !== "github"} icon={<ExportOutlined />} loading={controller.busy} type="primary">确认创建 PR</Button>
            </Popconfirm>
          </div>
          {planned && plan ? (
            <Alert
              showIcon
              type={plan.status === "created" ? "success" : "warning"}
              message={`${plan.provider} · ${plan.status}`}
              description={`${plan.base_branch} ← ${plan.head_branch ?? "当前分支"} · ${plan.commit_sha.slice(0, 12)}`}
            />
          ) : null}
        </div>
      </div>
    </section>
  );
}
