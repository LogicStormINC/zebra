import type { SessionEvent } from "../types";
import { ZebraApiError } from "./zebra-api";

export interface ChatMessage {
  key: string;
  role: "assistant" | "user";
  status?: "success" | "error" | "loading";
  content: string;
}

export interface ConversationSeed {
  key: string;
  label: string;
  group: string;
}

export const DEFAULT_CONVERSATIONS: ConversationSeed[] = [
  {
    key: "default-0",
    label: "查看项目文档",
    group: "置顶",
  },
  {
    key: "default-1",
    label: "修复本地会话流程",
    group: "置顶",
  },
  {
    key: "default-2",
    label: "对齐 Codex 风格桌面 UI",
    group: "置顶",
  },
];

function readText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function toErrorMessage(error: unknown): string {
  if (error instanceof ZebraApiError && typeof error.payload === "object" && error.payload && "reason" in error.payload) {
    return `${String(error.payload.reason)} (HTTP ${error.statusCode})`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown error";
}

export function isAppendToTerminalError(error: unknown): boolean {
  if (!(error instanceof ZebraApiError) || typeof error.payload !== "object" || error.payload === null) {
    return false;
  }
  const payload = error.payload as { status?: unknown; reason?: unknown };
  return (
    error.statusCode === 409 &&
    payload.status === "not_appendable" &&
    payload.reason === "cannot_append_to_terminal_session"
  );
}

export function streamEventsToMessages(events: SessionEvent[]): ChatMessage[] {
  return [...events]
    .sort((left, right) => left.sequence - right.sequence)
    .flatMap((event): ChatMessage[] => {
      if (event.event_type === "user_message_received") {
        const content = readText(event.payload.content);
        if (!content) {
          return [];
        }
        return [
          {
            key: event.event_id,
            role: "user",
            status: "success",
            content,
          },
        ];
      }
      if (event.event_type === "model_response_received") {
        const content = readText(event.payload.assistant_message);
        if (!content) {
          return [];
        }
        return [
          {
            key: event.event_id,
            role: "assistant",
            status: "success",
            content,
          },
        ];
      }
      return [];
    });
}
