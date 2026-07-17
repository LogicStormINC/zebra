import { ZebraApiError } from "./zebra-api";

export { streamEventsToMessages } from "./streaming-messages";

export interface ChatMessage {
  key: string;
  role: "assistant" | "user";
  status?: "success" | "error";
  content: string;
}

export interface ConversationSeed {
  key: string;
  label: string;
  group: string;
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
