import type { ChatMessage } from "../../lib/chat-surface";
import type { ApprovalSummary, SessionEvent, SessionSummary } from "../../types";
import { useConversationPaneStyle } from "../CodexConversationPane.styles";
import { SessionThreadWorkspace } from "../SessionThreadWorkspace";

interface ConversationThreadProps {
  activeApproval: ApprovalSummary | undefined;
  activeLabel: string;
  approvalBusy: boolean;
  approvalErrorText: string | null;
  clarificationBusy: boolean;
  composer: React.ReactNode;
  events: SessionEvent[];
  isDraft: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
  messages: ChatMessage[];
  onApprove: (approval: ApprovalSummary) => Promise<unknown>;
  onReject: (approval: ApprovalSummary) => Promise<unknown>;
  onRespondClarification: (clarificationId: string, content: string) => Promise<unknown>;
  sessionSummary: SessionSummary | null;
}

export function ConversationThread({
  activeApproval,
  activeLabel,
  approvalBusy,
  approvalErrorText,
  clarificationBusy,
  composer,
  events,
  isDraft,
  listRef,
  messages,
  onApprove,
  onReject,
  onRespondClarification,
  sessionSummary,
}: ConversationThreadProps) {
  const { styles } = useConversationPaneStyle();

  return (
    <>
      <div className={styles.stream} ref={listRef}>
        <div className={styles.streamInner}>
          <SessionThreadWorkspace
            activeApproval={activeApproval}
            activeLabel={activeLabel}
            approvalBusy={approvalBusy}
            approvalErrorText={approvalErrorText}
            clarificationBusy={clarificationBusy}
            events={events}
            isDraft={isDraft}
            messages={messages}
            onApprove={onApprove}
            onReject={onReject}
            onRespondClarification={onRespondClarification}
            sessionSummary={sessionSummary}
          />
        </div>
      </div>
      {sessionSummary?.status !== "waiting_input" ? <div className={styles.composerDock}>{composer}</div> : null}
    </>
  );
}
