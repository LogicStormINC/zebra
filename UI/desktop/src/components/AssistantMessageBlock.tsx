import { AssistantMessage } from "@zebra-agent/task-ui/react";
import type { ChatMessage } from "@zebra-agent/task-ui";
import "@ant-design/x-markdown/themes/dark.css";
import { AssistantInsightCards } from "./AssistantInsightCards";

export function AssistantMessageBlock({ message }: { message: ChatMessage }) {
  return (
    <AssistantMessage
      message={message}
      renderBefore={<AssistantInsightCards content={message.content} />}
    />
  );
}
