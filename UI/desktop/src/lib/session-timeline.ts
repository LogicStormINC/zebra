import type { SessionEvent } from "../types";
import type { ChatMessage } from "./chat-surface";

interface TimelineBase {
  key: string;
  sequence: number;
  createdAt: string;
}

export interface TimelineMessageItem extends TimelineBase {
  kind: "message";
  role: "user" | "assistant";
  content: string;
}

export type TimelineToolStatus =
  | "proposed"
  | "awaiting_approval"
  | "denied"
  | "running"
  | "completed"
  | "failed";

export interface TimelineToolItem extends TimelineBase {
  kind: "tool";
  attemptNumber: number;
  toolCallId?: string;
  toolName: string;
  status: TimelineToolStatus;
  arguments: Record<string, unknown>;
  policyDecision?: string;
  policyReason?: string;
  resultStatus?: string;
  output: string;
  metadata: Record<string, unknown>;
  eventIds: string[];
  lastSequence: number;
}

export interface TimelineStatusItem extends TimelineBase {
  kind: "status";
  eventType: string;
  attemptNumber?: number;
}

export type TimelineItem = TimelineMessageItem | TimelineToolItem | TimelineStatusItem;

export type TimelinePlanPlacement =
  | { mode: "replace" | "after"; anchorKey: string }
  | { mode: "start" };

const TOOL_EVENTS = new Set([
  "tool_call_proposed",
  "policy_decision_made",
  "tool_execution_started",
  "tool_execution_completed",
  "tool_execution_failed",
]);

const STATUS_EVENTS = new Set([
  "session_created",
  "plan_proposed",
  "plan_updated",
  "model_request_started",
  "harness_attempt_started",
  "approval_requested",
  "approval_granted",
  "approval_rejected",
  "clarification_requested",
  "clarification_responded",
  "tests_completed",
  "session_suspended",
  "session_resumed",
  "session_completed",
  "session_failed",
  "session_cancelled",
]);

interface ToolBuilder extends TimelineToolItem {
  hasPolicy: boolean;
  hasStarted: boolean;
  hasTerminal: boolean;
}

function objectValue(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function attemptNumber(event: SessionEvent): number | undefined {
  const value = event.payload.attempt_number;
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : undefined;
}

export function isVisibleSessionEvent(event: SessionEvent): boolean {
  return !(
    event.event_type === "tests_completed"
    && objectValue(event.payload).summary === "verifier hook skipped"
  );
}

function toolStatus(tool: ToolBuilder): TimelineToolStatus {
  if (tool.hasTerminal) return tool.status;
  if (tool.hasStarted) return "running";
  if (tool.policyDecision === "deny") return "denied";
  if (tool.policyDecision === "require_approval") return "awaiting_approval";
  return "proposed";
}

function snapshotTool(tool: ToolBuilder): TimelineToolItem {
  return {
    kind: tool.kind,
    key: tool.key,
    sequence: tool.sequence,
    createdAt: tool.createdAt,
    attemptNumber: tool.attemptNumber,
    toolCallId: tool.toolCallId,
    toolName: tool.toolName,
    status: tool.status,
    arguments: tool.arguments,
    policyDecision: tool.policyDecision,
    policyReason: tool.policyReason,
    resultStatus: tool.resultStatus,
    output: tool.output,
    metadata: tool.metadata,
    eventIds: tool.eventIds,
    lastSequence: tool.lastSequence,
  };
}

export function projectSessionTimeline(events: SessionEvent[]): TimelineItem[] {
  const ordered = events
    .map((event, index) => ({ event, index }))
    .sort((left, right) => left.event.sequence - right.event.sequence || left.index - right.index);
  const seenEventIds = new Set<string>();
  const items: TimelineItem[] = [];
  const toolsById = new Map<string, ToolBuilder>();
  const tools: ToolBuilder[] = [];

  const createTool = (event: SessionEvent, attempt: number, name: string, callId?: string) => {
    const tool: ToolBuilder = {
      kind: "tool",
      key: callId ? `tool:${attempt}:${callId}` : `tool:${event.event_id}`,
      sequence: event.sequence,
      createdAt: event.created_at,
      attemptNumber: attempt,
      toolCallId: callId,
      toolName: name,
      status: "proposed",
      arguments: {},
      output: "",
      metadata: {},
      eventIds: [],
      lastSequence: event.sequence,
      hasPolicy: false,
      hasStarted: false,
      hasTerminal: false,
    };
    tools.push(tool);
    items.push(tool);
    if (callId) toolsById.set(`${attempt}:${callId}`, tool);
    return tool;
  };

  const findTool = (event: SessionEvent, phase: "policy" | "started" | "terminal") => {
    const attempt = attemptNumber(event);
    const name = stringValue(event.payload.tool_name);
    if (!attempt || !name) return undefined;
    const callId = stringValue(event.payload.tool_call_id);
    if (callId) return toolsById.get(`${attempt}:${callId}`) ?? createTool(event, attempt, name, callId);
    return tools.find((tool) => {
      if (tool.attemptNumber !== attempt || tool.toolName !== name || tool.toolCallId) return false;
      if (phase === "policy") return !tool.hasPolicy;
      if (tool.hasTerminal) return false;
      return phase === "started" ? !tool.hasStarted : true;
    }) ?? createTool(event, attempt, name);
  };

  for (const { event: sourceEvent } of ordered) {
    if (seenEventIds.has(sourceEvent.event_id)) continue;
    seenEventIds.add(sourceEvent.event_id);
    if (!isVisibleSessionEvent(sourceEvent)) continue;
    const event = { ...sourceEvent, payload: objectValue(sourceEvent.payload) };

    if (
      event.event_type === "user_message_received"
      || event.event_type === "clarification_responded"
      || event.event_type === "model_response_received"
    ) {
      const isAssistant = event.event_type === "model_response_received";
      const content = stringValue(event.payload[isAssistant ? "assistant_message" : "content"]);
      if (content?.trim()) {
        items.push({
          kind: "message",
          key: `message:${event.event_id}`,
          sequence: event.sequence,
          createdAt: event.created_at,
          role: isAssistant ? "assistant" : "user",
          content,
        });
        continue;
      }
      if (event.event_type !== "clarification_responded") continue;
    }

    if (TOOL_EVENTS.has(event.event_type)) {
      const phase = event.event_type === "policy_decision_made"
        ? "policy"
        : event.event_type === "tool_execution_started" ? "started" : event.event_type === "tool_call_proposed" ? null : "terminal";
      const attempt = attemptNumber(event);
      const name = stringValue(event.payload.tool_name);
      if (!attempt || !name) continue;
      const callId = stringValue(event.payload.tool_call_id);
      const tool = phase === null
        ? (callId ? toolsById.get(`${attempt}:${callId}`) : undefined) ?? createTool(event, attempt, name, callId)
        : findTool(event, phase);
      if (!tool) continue;
      tool.eventIds.push(event.event_id);
      tool.lastSequence = event.sequence;
      if (event.event_type === "tool_call_proposed") tool.arguments = objectValue(event.payload.arguments);
      if (event.event_type === "policy_decision_made") {
        tool.hasPolicy = true;
        tool.policyDecision = stringValue(event.payload.decision);
        tool.policyReason = stringValue(event.payload.reason);
      }
      if (event.event_type === "tool_execution_started") tool.hasStarted = true;
      if (event.event_type === "tool_execution_completed" || event.event_type === "tool_execution_failed") {
        tool.hasTerminal = true;
        tool.status = event.event_type === "tool_execution_failed" ? "failed" : "completed";
        tool.resultStatus = stringValue(event.payload.status);
        tool.output = stringValue(event.payload.output) ?? "";
        tool.metadata = objectValue(event.payload.metadata);
      }
      tool.status = toolStatus(tool);
      continue;
    }

    if (STATUS_EVENTS.has(event.event_type)) {
      items.push({
        kind: "status",
        key: `status:${event.event_id}`,
        sequence: event.sequence,
        createdAt: event.created_at,
        eventType: event.event_type,
        attemptNumber: attemptNumber(event),
      });
    }
  }

  return items
    .sort((left, right) => left.sequence - right.sequence)
    .map((item) => item.kind === "tool" ? snapshotTool(item as ToolBuilder) : item);
}

export function timelinePlanPlacement(timeline: TimelineItem[]): TimelinePlanPlacement {
  let latestPlanEvent: TimelineStatusItem | undefined;
  for (const item of timeline) {
    if (item.kind === "status" && (item.eventType === "plan_proposed" || item.eventType === "plan_updated")) {
      latestPlanEvent = item;
    }
  }
  if (latestPlanEvent) return { mode: "replace", anchorKey: latestPlanEvent.key };
  const firstUserMessage = timeline.find((item) => item.kind === "message" && item.role === "user");
  if (firstUserMessage) return { mode: "after", anchorKey: firstUserMessage.key };
  // ponytail: restored plans can predate retained events, so start-of-stream is the only truthful stable fallback.
  return { mode: "start" };
}

export function optimisticTimelineMessages(
  timeline: TimelineItem[],
  messages: ChatMessage[],
): ChatMessage[] {
  const messageItems = timeline.filter((item): item is TimelineMessageItem => item.kind === "message");
  const eventIds = new Set(messageItems.map((item) => item.key.slice("message:".length)));
  const signature = (role: ChatMessage["role"], content: string) => `${role}\u0000${content.trim()}`;
  const projected = new Set(messageItems.map((item) => signature(item.role, item.content)));
  const backedPositions = new Map<string, number[]>();

  messages.forEach((message, index) => {
    if (!eventIds.has(message.key)) return;
    const key = signature(message.role, message.content);
    backedPositions.set(key, [...(backedPositions.get(key) ?? []), index]);
  });

  return messages.filter((message, index) => {
    if (eventIds.has(message.key)) return false;
    const key = signature(message.role, message.content);
    if (!projected.has(key)) return true;
    const positions = backedPositions.get(key);
    return Boolean(positions?.length && positions.every((position) => position < index));
  });
}
