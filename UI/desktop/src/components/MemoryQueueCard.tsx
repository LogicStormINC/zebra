import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Input,
  Radio,
  Space,
  Spin,
  Typography,
} from "antd";
import { createStyles } from "antd-style";
import type {
  MemoryQueuePreviewResponse,
  MemoryQueueReviewResponse,
  MemoryScopeKind,
} from "../types";
import type { ZebraApiClient } from "../lib/zebra-api";
import {
  buildMemoryScopeOptions,
  type MemoryScopeOption,
} from "../lib/use-memory-scope-surface";
import { MemoryQueuePreviewPanel, MemoryQueueReviewPanel } from "./MemoryQueuePanels";
import { formatOperatorError } from "../lib/use-operator-workbench";

const useStyle = createStyles(({ css }) => ({
  secondaryText: css`
    margin-bottom: 0;
    color: rgba(255, 255, 255, 0.58) !important;
  `,
  titleBlock: css`
    margin-top: var(--zebra-space-2xs);
  `,
  loadingArea: css`
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: calc(var(--zebra-space-xl) + var(--zebra-space-xl));
  `,
  inputSmall: css`
    min-width: min(100%, var(--zebra-sidebar-width-min));
  `,
  inputWide: css`
    min-width: min(100%, var(--zebra-sidebar-width-max));
    flex: 1;
  `,
}));

interface MemoryQueueCardProps {
  api: ZebraApiClient;
  sessionId: string;
  userId: string;
  tenantId: string;
  disabled: boolean;
  onRefresh: () => Promise<void> | void;
}

export function MemoryQueueCard({
  api,
  sessionId,
  userId,
  tenantId,
  disabled,
  onRefresh,
}: MemoryQueueCardProps) {
  const { message } = AntApp.useApp();
  const scopes = useMemo(() => buildMemoryScopeOptions(sessionId, userId, tenantId), [sessionId, userId, tenantId]);
  const [selectedScope, setSelectedScope] = useState<MemoryScopeKind>("session");
  const [decision, setDecision] = useState<"confirm" | "expire">("confirm");
  const [memoryType, setMemoryType] = useState("");
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<MemoryQueuePreviewResponse | null>(null);
  const [review, setReview] = useState<MemoryQueueReviewResponse | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const { styles } = useStyle();

  useEffect(() => {
    if (!scopes.length) {
      setSelectedScope("session");
      return;
    }
    if (!scopes.some((scope) => scope.kind === selectedScope)) {
      setSelectedScope(scopes[0].kind);
    }
  }, [scopes, selectedScope]);
  const activeScope = scopes.find((scope) => scope.kind === selectedScope) ?? null;

  async function callPreview(scope: MemoryScopeOption): Promise<MemoryQueuePreviewResponse> {
    const payload = {
      decision,
      memory_type: memoryType.trim() || undefined,
    };
    switch (scope.kind) {
      case "session":
        return api.previewSessionMemoryQueue(scope.targetId, payload);
      case "user":
        return api.previewUserMemoryQueue(scope.targetId, payload);
      case "tenant":
        return api.previewTenantMemoryQueue(scope.targetId, payload);
    }
  }

  async function callSweep(scope: MemoryScopeOption): Promise<MemoryQueueReviewResponse> {
    const payload = {
      decision,
      operator: operator.trim() || undefined,
      reason: reason.trim() || undefined,
    };
    switch (scope.kind) {
      case "session":
        return api.reviewSessionMemoryQueue(scope.targetId, payload);
      case "user":
        return api.reviewUserMemoryQueue(scope.targetId, payload);
      case "tenant":
        return api.reviewTenantMemoryQueue(scope.targetId, payload);
    }
  }

  async function callBulkReview(scope: MemoryScopeOption): Promise<MemoryQueueReviewResponse> {
    const payload = {
      decision,
      operator: operator.trim() || undefined,
      reason: reason.trim() || undefined,
      memory_ids: selectedIds,
    };
    switch (scope.kind) {
      case "session":
        return api.bulkReviewSessionMemory(scope.targetId, payload);
      case "user":
        return api.bulkReviewUserMemory(scope.targetId, payload);
      case "tenant":
        return api.bulkReviewTenantMemory(scope.targetId, payload);
    }
  }

  async function runAction<T>(action: () => Promise<T>, onSuccess: (result: T) => void, successText: string) {
    setLoading(true);
    setErrorText(null);
    try {
      const result = await action();
      onSuccess(result);
      await onRefresh();
      message.success(successText);
    } catch (error) {
      const formatted = formatOperatorError(error);
      setErrorText(formatted);
      message.error(formatted);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card title="Memory Queue Operations">
      <Space direction="vertical" size="large" className="w-full">
        <Typography.Paragraph className={styles.secondaryText}>
          Preview queued candidate memories for the active scope, then either sweep the full queue or bulk-review a selected subset.
        </Typography.Paragraph>
        {errorText ? <Alert type="warning" showIcon message="Memory queue request failed" description={errorText} /> : null}
        {!scopes.length ? (
          <Alert
            type="info"
            showIcon
            message="No memory scope available"
            description="Provide at least one session id, user id, or tenant id in the operator config."
          />
        ) : (
          <>
            <Space direction="vertical" size="middle" className="w-full">
              <div>
                <Typography.Text strong>Scope</Typography.Text>
                <Radio.Group
                  className={styles.titleBlock}
                  optionType="button"
                  buttonStyle="solid"
                  value={selectedScope}
                  onChange={(event) => {
                    setSelectedScope(event.target.value);
                    setPreview(null);
                    setReview(null);
                    setSelectedIds([]);
                    setErrorText(null);
                  }}
                  options={scopes.map((scope) => ({
                    label: `${scope.label}: ${scope.targetId}`,
                    value: scope.kind,
                  }))}
                />
              </div>
              <div>
                <Typography.Text strong>Decision</Typography.Text>
                <Radio.Group
                  className={styles.titleBlock}
                  optionType="button"
                  buttonStyle="solid"
                  value={decision}
                  onChange={(event) => setDecision(event.target.value)}
                  options={[
                    { label: "Confirm", value: "confirm" },
                    { label: "Expire", value: "expire" },
                  ]}
                />
              </div>
              <Space wrap className="w-full">
                <Input
                  className={styles.inputSmall}
                  placeholder="memory_type filter, e.g. procedure"
                  value={memoryType}
                  onChange={(event) => setMemoryType(event.target.value)}
                  disabled={disabled || loading}
                />
                <Input
                  className={styles.inputSmall}
                  placeholder="operator (optional)"
                  value={operator}
                  onChange={(event) => setOperator(event.target.value)}
                  disabled={disabled || loading}
                />
                <Input
                  className={styles.inputWide}
                  placeholder="reason (optional)"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  disabled={disabled || loading}
                />
              </Space>
              <Space wrap>
                <Button
                  type="primary"
                  disabled={disabled || loading || activeScope === null}
                  onClick={() =>
                    activeScope &&
                    void runAction(
                      () => callPreview(activeScope),
                      (result) => {
                        setPreview(result);
                        setReview(null);
                        setSelectedIds(result.memory_ids);
                      },
                      `Preview ready: ${activeScope.kind} queue`,
                    )
                  }
                >
                  Preview queue
                </Button>
                <Button
                  disabled={disabled || loading || activeScope === null}
                  onClick={() =>
                    activeScope &&
                    void runAction(
                      () => callSweep(activeScope),
                      (result) => setReview(result),
                      `Queue sweep complete: ${activeScope.kind}`,
                    )
                  }
                >
                  Sweep queued memories
                </Button>
                <Button
                  danger={decision === "expire"}
                  disabled={disabled || loading || activeScope === null || selectedIds.length === 0}
                  onClick={() =>
                    activeScope &&
                    void runAction(
                      () => callBulkReview(activeScope),
                      (result) => setReview(result),
                      `Bulk review complete: ${selectedIds.length} requested`,
                    )
                  }
                >
                  Bulk review selected
                </Button>
              </Space>
            </Space>
            {loading ? (
              <div className={styles.loadingArea}>
                <Spin />
              </div>
            ) : null}
            {preview ? (
              <MemoryQueuePreviewPanel
                preview={preview}
                selectedIds={selectedIds}
                onSelectAll={() => setSelectedIds(preview.memory_ids)}
                onClearSelection={() => setSelectedIds([])}
                onToggleSelection={(memoryId, checked) =>
                  setSelectedIds((current) =>
                    checked
                      ? current.includes(memoryId)
                        ? current
                        : [...current, memoryId]
                      : current.filter((item) => item !== memoryId),
                  )
                }
              />
            ) : null}
            {review ? <MemoryQueueReviewPanel review={review} /> : null}
          </>
        )}
      </Space>
    </Card>
  );
}
