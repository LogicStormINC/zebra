/** Human-in-the-loop hooks mapping Zebra interrupts to React UI. */

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useRef,
  type ReactNode,
} from "react";

export interface ApprovalRequestWire {
  approval_id: string;
  tool_name: string;
  reason: string;
}

export interface ClarificationRequestWire {
  clarification_id: string;
  question: string;
  choices: string[];
}

interface HitlContextValue {
  approval: ApprovalRequestWire | null;
  clarification: ClarificationRequestWire | null;
  controller: boolean;
  decide: (
    decision: "approve" | "reject",
    onIdempotencyKey: string,
  ) => Promise<void>;
  respond: (choice: string, idempotencyKey: string) => Promise<void>;
}

const HitlContext = createContext<HitlContextValue | null>(null);

export function ZebraHitlProvider(props: {
  children: ReactNode;
  approval?: ApprovalRequestWire | null;
  clarification?: ClarificationRequestWire | null;
  controller: boolean;
  onDecide: (decision: "approve" | "reject", key: string) => Promise<void>;
  onRespond: (choice: string, key: string) => Promise<void>;
}) {
  const approval = props.approval ?? null;
  const clarification = props.clarification ?? null;
  const decide = useCallback(
    async (decision: "approve" | "reject", key: string) => {
      await props.onDecide(decision, key);
    },
    [props],
  );
  const respond = useCallback(
    async (choice: string, key: string) => {
      await props.onRespond(choice, key);
    },
    [props],
  );
  return createElement(
    HitlContext.Provider,
    { value: { approval, clarification, controller: props.controller, decide, respond } },
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
  const decided = useRef(false);
  useEffect(() => {
    decided.current = false;
  }, [context.approval?.approval_id]);
  const decide = useCallback(
    async (decision: "approve" | "reject") => {
      if (!context.controller) throw new Error("observer cannot decide approvals");
      if (context.approval === null) throw new Error("no active approval request");
      if (decided.current) return; // duplicate click: one decision only
      decided.current = true;
      try {
        await context.decide(
          decision,
          `hitl-approval:${context.approval.approval_id}`,
        );
      } catch (error) {
        decided.current = false;
        throw error;
      }
    },
    [context],
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
  const responded = useRef(false);
  useEffect(() => {
    responded.current = false;
  }, [context.clarification?.clarification_id]);
  const respond = useCallback(
    async (choice: string) => {
      if (!context.controller) throw new Error("observer cannot answer clarifications");
      if (context.clarification === null) {
        throw new Error("no active clarification request");
      }
      if (!context.clarification.choices.includes(choice)) {
        throw new Error("clarification choice is outside the request contract");
      }
      if (responded.current) return;
      responded.current = true;
      try {
        await context.respond(
          choice,
          `hitl-clarification:${context.clarification.clarification_id}`,
        );
      } catch (error) {
        responded.current = false;
        throw error;
      }
    },
    [context],
  );
  return { clarification: context.clarification, respond };
}
