import type { ChatMessage } from "../../lib/chat-surface";
import type { ApprovalSummary, SessionEvent, SessionHandoffPayload, SessionHandoffResponse, SessionSummary } from "../../types";
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
  isRequesting: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
  messages: ChatMessage[];
  onApprove: (approval: ApprovalSummary) => Promise<unknown>;
  onReject: (approval: ApprovalSummary) => Promise<unknown>;
  onPreviewHandoff: (payload: SessionHandoffPayload) => Promise<SessionHandoffResponse>;
  onCreateHandoff: (payload: SessionHandoffPayload) => Promise<SessionHandoffResponse>;
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
  isRequesting,
  listRef,
  messages,
  onApprove,
  onReject,
  onPreviewHandoff,
  onCreateHandoff,
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
            isRequesting={isRequesting}
            messages={messages}
            onApprove={onApprove}
            onReject={onReject}
            onPreviewHandoff={onPreviewHandoff}
            onCreateHandoff={onCreateHandoff}
            onRespondClarification={onRespondClarification}
            sessionSummary={sessionSummary}
          />
        </div>
      </div>
      {sessionSummary?.status !== "waiting_input" ? <div className={styles.composerDock}>{composer}</div> : null}
    </>
  );
}
