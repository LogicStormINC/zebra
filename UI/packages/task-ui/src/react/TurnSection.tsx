import { createStyles } from "antd-style";
import type { ReactNode } from "react";
import {
  defaultTurnDisclosure,
  type TurnDisclosure,
  type TurnStatus,
} from "../core/turn-disclosure.ts";

const useStyle = createStyles(({ css }) => ({
  section: css`
    min-width: 0;
  `,
  body: css`
    display: grid;
  `,
}));

interface TurnSectionProps {
  /** Turn identity, used as the section key when rendering lists. */
  turnId: string;
  status: TurnStatus;
  /** Optional consumer-provided header (e.g. elapsed time row). */
  header?: ReactNode;
  /** Overrides the deterministic status default when provided. */
  disclosure?: TurnDisclosure;
  children: ReactNode;
}

/**
 * Generic turn wrapper applying the deterministic disclosure default:
 * running open, succeeded collapsed, waiting/failed/canceled open.
 * The collapsed body stays mounted (hidden via the native details element),
 * so a terminal GET can reconcile content without losing state.
 */
export function TurnSection({
  turnId,
  status,
  header,
  disclosure,
  children,
}: TurnSectionProps) {
  const { styles } = useStyle();
  const resolved = disclosure ?? defaultTurnDisclosure(status);
  return (
    <details
      className={styles.section}
      data-turn-id={turnId}
      data-status={status}
      data-disclosure={resolved}
      open={resolved === "open" || undefined}
    >
      {header ? <summary>{header}</summary> : null}
      <div className={styles.body}>{children}</div>
    </details>
  );
}
