import type { ChatMessage, SessionEvent } from "./public-types.ts";

function readText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

const STREAM_RESET_EVENTS = new Set([
  "model_request_started",
  "harness_attempt_started",
  "approval_requested",
  "clarification_requested",
  "session_suspended",
  "session_completed",
  "session_failed",
  "session_cancelled",
]);

/**
 * Reduce raw task events into display messages: sequence-ordered merge,
 * delta chunk assembly, and in-place streaming-final replacement.
 */
export function streamEventsToMessages(events: SessionEvent[]): ChatMessage[] {
  const messages = new Map<string, { message: ChatMessage; sequence: number }>();
  const streamed = new Map<string, {
    chunks: Map<number, string>;
    key: string;
    sequence: number;
  }>();
  const discardUncommittedStreams = () => {
    for (const draft of streamed.values()) messages.delete(draft.key);
    streamed.clear();
  };
  [...events]
    .sort((left, right) => left.sequence - right.sequence)
    .forEach((event) => {
      if (
        event.event_type === "user_message_received"
        || event.event_type === "clarification_responded"
      ) {
        const content = readText(event.payload.content);
        if (content) {
          messages.set(event.event_id, {
            sequence: event.sequence,
            message: {
              key: event.event_id,
              role: "user",
              status: "success",
              content,
            },
          });
        }
        return;
      }
      if (STREAM_RESET_EVENTS.has(event.event_type)) {
        discardUncommittedStreams();
        return;
      }
      if (event.event_type === "model_response_delta") {
        const modelCallId = readText(event.payload.model_call_id);
        const delta = typeof event.payload.content_delta === "string"
          ? event.payload.content_delta
          : "";
        const deltaIndex = event.payload.delta_index;
        if (!modelCallId || !delta || typeof deltaIndex !== "number") return;
        const current = streamed.get(modelCallId) ?? {
          chunks: new Map<number, string>(),
          key: `model-stream:${modelCallId}`,
          sequence: event.sequence,
        };
        current.chunks.set(deltaIndex, delta);
        streamed.set(modelCallId, current);
        messages.set(current.key, {
          sequence: current.sequence,
          message: {
            key: current.key,
            role: "assistant",
            status: "success",
            content: [...current.chunks.entries()]
              .sort(([left], [right]) => left - right)
              .map(([, content]) => content)
              .join(""),
          },
        });
        return;
      }
      if (event.event_type !== "model_response_received") return;
      const modelCallId = readText(event.payload.model_call_id);
      const partial = modelCallId ? streamed.get(modelCallId) : undefined;
      discardUncommittedStreams();
      const content = readText(event.payload.assistant_message);
      if (!content) return;
      messages.set(event.event_id, {
        sequence: partial?.sequence ?? event.sequence,
        message: {
          key: event.event_id,
          role: "assistant",
          status: "success",
          content,
        },
      });
    });
  return [...messages.values()]
    .sort((left, right) => left.sequence - right.sequence)
    .map(({ message }) => message);
}
