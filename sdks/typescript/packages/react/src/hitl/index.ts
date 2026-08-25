/** Human-in-the-loop hooks mapping Zebra interrupts to React UI. */

import {
  createElement,
  useCallback,
  useContext,
  createContext,
  useState,
  type ReactNode,
} from "react";

interface ApprovalRequestWire {
  approval_id: string;
  tool_name: string;
  reason: string;
}

interface ClarificationRequestWire {
  clarification_id: string;
  question: string;
  choices: string[];
}

interface HitlContextValue {
  approval: ApprovalRequestWire | null;
  clarification: ClarificationRequestWire | null;
  decide: (
    decision: "approve" | "reject",
    onIdempotencyKey: string,
  ) => Promise<void>;
  respond: (choice: string, idempotencyKey: string) => Promise<void>;
}

const HitlContext = createContext<HitlContextValue | null>(null);

export function ZebraHitlProvider(props: {
  children: ReactNode;
  onDecide: (decision: "approve" | "reject", key: string) => Promise<void>;
  onRespond: (choice: string, key: string) => Promise<void>;
}) {
  const [approval, setApproval] = useState<ApprovalRequestWire | null>(null);
  const [clarification, setClarification] =
    useState<ClarificationRequestWire | null>(null);
  const decide = useCallback(
    async (decision: "approve" | "reject", key: string) => {
      await props.onDecide(decision, key);
      setApproval(null);
    },
    [props],
  );
  const respond = useCallback(
    async (choice: string, key: string) => {
      await props.onRespond(choice, key);
      setClarification(null);
    },
    [props],
  );
  return createElement(
    HitlContext.Provider,
    { value: { approval, clarification, decide, respond } },
    props.children,
  );
}

/** Custom-renderable approval surface; double clicks submit once. */
export function useZebraApproval(): {
  approval: ApprovalRequestWire | null;
  decide: (decision: "approve" | "reject") => Promise<void>;
} {
  const context = useContext(HitlContext);
  if (context === null) {
    throw new Error("useZebraApproval requires <ZebraHitlProvider>");
  }
  const decided = useState({ sent: false })[0];
  const decide = useCallback(
    async (decision: "approve" | "reject") => {
      if (decided.sent) return; // duplicate click: one decision only
      decided.sent = true;
      await context.decide(
        decision,
        `hitl-approval:${context.approval?.approval_id ?? "unknown"}`,
      );
    },
    [context, decided],
  );
  return { approval: context.approval, decide };
}

export function useZebraClarification(): {
  clarification: ClarificationRequestWire | null;
  respond: (choice: string) => Promise<void>;
} {
  const context = useContext(HitlContext);
  if (context === null) {
    throw new Error("useZebraClarification requires <ZebraHitlProvider>");
  }
  const respond = useCallback(
    async (choice: string) => {
      await context.respond(
        choice,
        `hitl-clarification:${context.clarification?.clarification_id ?? "unknown"}`,
      );
    },
    [context],
  );
  return { clarification: context.clarification, respond };
}
