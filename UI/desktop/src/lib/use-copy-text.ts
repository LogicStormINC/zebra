import React from "react";
import { toErrorMessage } from "./chat-surface";

interface MessageSink {
  error: (content: string) => unknown;
  success: (content: string) => unknown;
}

export function useCopyText(messages: MessageSink) {
  return React.useCallback(
    async (value: string, successText: string) => {
      try {
        await navigator.clipboard.writeText(value);
        messages.success(successText);
      } catch (error: unknown) {
        messages.error(toErrorMessage(error));
      }
    },
    [messages],
  );
}
