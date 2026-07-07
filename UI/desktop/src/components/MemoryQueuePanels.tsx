import { Button, Checkbox, Empty, List, Space, Statistic, Tag, Typography } from "antd";
import { createStyles } from "antd-style";
import type { MemoryQueuePreviewResponse, MemoryQueueReviewResponse } from "../types";

const useStyle = createStyles(({ css }) => ({
  titleBlock: css`
    margin-bottom: 0;
  `,
}));

interface MemoryQueuePreviewPanelProps {
  preview: MemoryQueuePreviewResponse;
  selectedIds: string[];
  onSelectAll: () => void;
  onClearSelection: () => void;
  onToggleSelection: (memoryId: string, checked: boolean) => void;
}

export function MemoryQueuePreviewPanel({
  preview,
  selectedIds,
  onSelectAll,
  onClearSelection,
  onToggleSelection,
}: MemoryQueuePreviewPanelProps) {
  const projectedResults = new Map(
    preview.projected_results.map((result) => [result.memory_id, result]),
  );
  const targetExplanations = new Map(
    preview.target_explanations.map((result) => [result.memory_id, result]),
  );

  return (
    <Space direction="vertical" size="middle" className="w-full">
      <Space size="large" wrap>
        <Statistic title="Queued count" value={preview.queued_count} />
        <Statistic title="Projected applied" value={preview.projected_applied_count} />
        <Statistic title="Selected ids" value={selectedIds.length} />
      </Space>
      <Space wrap>
        <Tag color="geekblue">{preview.target_scope_kind}</Tag>
        <Tag>{preview.target_scope_id}</Tag>
        <Tag color={preview.decision === "confirm" ? "green" : "red"}>
          {preview.projected_memory_status}
        </Tag>
        {preview.memory_type_filter ? <Tag color="purple">{preview.memory_type_filter}</Tag> : null}
      </Space>
      <Space wrap>
        <Button size="small" onClick={onSelectAll}>
          Select all
        </Button>
        <Button size="small" onClick={onClearSelection}>
          Clear selection
        </Button>
      </Space>
      <List
        dataSource={preview.memories}
        locale={{ emptyText: <Empty description="No queued memories matched this preview." /> }}
        renderItem={(memory) => {
          const explanation = targetExplanations.get(memory.memory_id);
          const projection = projectedResults.get(memory.memory_id);
          return (
            <List.Item>
              <Space align="start" size="middle" className="w-full">
                <Checkbox
                  checked={selectedIds.includes(memory.memory_id)}
                  onChange={(event) => onToggleSelection(memory.memory_id, event.target.checked)}
                />
                <Space direction="vertical" size={4} className="w-full">
                  <Space wrap>
                    <Tag color="blue">{memory.memory_type}</Tag>
                    <Tag>{memory.status}</Tag>
                    <Tag>{memory.visibility}</Tag>
                    {projection ? <Tag color="green">{projection.projected_status}</Tag> : null}
                  </Space>
                  <Typography.Text>{memory.text}</Typography.Text>
                  <Typography.Text type="secondary">
                    {explanation?.target_reason ?? "no target explanation"} · {memory.updated_at}
                  </Typography.Text>
                </Space>
              </Space>
            </List.Item>
          );
        }}
      />
    </Space>
  );
}

interface MemoryQueueReviewPanelProps {
  review: MemoryQueueReviewResponse;
}

export function MemoryQueueReviewPanel({ review }: MemoryQueueReviewPanelProps) {
  const { styles } = useStyle();
  return (
    <Space direction="vertical" size="middle" className="w-full">
      <Typography.Title level={5} className={styles.titleBlock}>
        Review Result
      </Typography.Title>
      <Space size="large" wrap>
        <Statistic title="Applied" value={review.applied_count} />
        <Statistic title="Skipped" value={review.skipped_count} />
        <Statistic title="Invalid" value={review.invalid_count} />
        <Statistic title="Requested" value={review.total_requested} />
      </Space>
      <List
        dataSource={review.results}
        renderItem={(result) => (
          <List.Item>
            <Space direction="vertical" size={4}>
              <Space wrap>
                <Tag
                  color={result.outcome === "applied" ? "green" : result.outcome === "invalid" ? "red" : "gold"}
                >
                  {result.outcome}
                </Tag>
                <Tag>{result.memory_id}</Tag>
                {result.status ? <Tag>{result.status}</Tag> : null}
                {result.memory_status ? <Tag color="blue">{result.memory_status}</Tag> : null}
              </Space>
              {result.reason ? <Typography.Text type="secondary">{result.reason}</Typography.Text> : null}
            </Space>
          </List.Item>
        )}
      />
    </Space>
  );
}
