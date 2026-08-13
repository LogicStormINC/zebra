import { ArrowDownOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { createStyles } from "antd-style";

const useStyle = createStyles(({ css }) => ({
  cue: css`
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 1px solid rgba(245, 158, 11, 0.35);
    border-radius: 999px;
    background: rgba(245, 158, 11, 0.12);
    color: #f5a623;
    font-size: 12px;
    line-height: 20px;
    padding: 2px 12px;
  `,
}));

interface NewContentCueProps {
  /** Called when the user clicks the cue to jump to the new content. */
  onDismiss: () => void;
  label?: string;
}

/**
 * Bare aria-live "new content" cue. Scroll anchoring stays consumer-side;
 * this primitive only announces and dismisses.
 */
export function NewContentCue({
  onDismiss,
  label = "有新内容",
}: NewContentCueProps) {
  const { styles } = useStyle();
  return (
    <div aria-live="polite">
      <Button
        aria-label={label}
        className={styles.cue}
        icon={<ArrowDownOutlined />}
        onClick={onDismiss}
        size="small"
        type="text"
      >
        {label}
      </Button>
    </div>
  );
}
