import type { AgentContentPart, AgentConversationItem, AgentConversationTurn, AgentMessage } from "@zebra-agent/ui-contracts";

/** Select replay revisions without moving the original message's timeline slot. */
export function selectConversationItems(turn: AgentConversationTurn): readonly AgentConversationItem[] {
  const source: readonly AgentConversationItem[] = turn.items ?? turn.workSegments.map((segment) => ({
    id: segment.id, kind: "activity", segment,
  }));
  const items = new Map<string, AgentConversationItem>();
  const messageKeys = new Map<string, string>();
  for (const item of source) {
    if (item.kind === "message" && item.message.id === turn.userMessage?.id) continue;
    const key = item.kind === "message" ? messageKeys.get(item.message.id) ?? item.id : item.id;
    const previous = items.get(key);
    const selected = { ...item, ...(previous ? { id: previous.id } : {}) };
    if (previous) {
      if (previous.sequence === undefined) delete selected.sequence;
      else selected.sequence = previous.sequence;
      if (previous.kind === "message" && selected.kind === "message") {
        selected.message = reviseMessage(previous.message, selected.message);
      }
    }
    items.set(key, selected);
    if (item.kind === "message") messageKeys.set(item.message.id, key);
  }
  const ordered = [...items.values()].filter(item => item.kind !== "status" || item.state.phase === "terminal" ||
    ["running", "queued", "waiting"].includes(turn.status)).sort((left, right) => {
    if (left.sequence === undefined) return right.sequence === undefined ? 0 : 1;
    if (right.sequence === undefined) return -1;
    return left.sequence - right.sequence;
  });
  const final = turn.assistantMessage;
  if (!final) return ordered;
  const key = messageKeys.get(final.id);
  if (key === undefined) {
    ordered.push({ id: final.id, kind: "message", message: final });
  } else {
    return ordered.map((item) => item.kind === "message" && item.id === key ? {
      ...item,
      message: reviseMessage(item.message, final),
    } : item);
  }
  return ordered;
}

function reviseMessage(previous: AgentMessage, current: AgentMessage): AgentMessage {
  if (previous === current) return current;
  if (current.parts !== undefined || !previous.parts?.length) return { ...previous, ...current };
  const textParts = previous.parts.filter((part) => part.type === "text");
  if ((textParts[0]?.state === "ready" && (textParts[0].text === current.content ||
      textParts.map((part) => part.text).join("\n") === current.content)) ||
      (!textParts.length && !current.content)) {
    return { ...previous, ...current, parts: previous.parts };
  }
  // ponytail: text-only corrections revise the first slot; supply parts to revise independent later slots.
  const text = textParts.slice(1).reduceRight((content, part) => part.text && content.endsWith(part.text) &&
    (content === part.text || /\s/.test(content.at(-part.text.length - 1) ?? ""))
    ? content.slice(0, -part.text.length).trimEnd()
    : content, current.content);
  if (textParts[0]?.state === "ready" && textParts[0].text === text) {
    return { ...previous, ...current, parts: previous.parts };
  }
  const parts: AgentContentPart[] = previous.parts.map((part) => part === textParts[0]
    ? { ...part, text, state: "ready" as const }
    : part);
  if (!textParts.length && current.content) {
    const ids = new Set(parts.map((part) => part.id));
    let id = `${current.id}:text`;
    for (let suffix = 1; ids.has(id); suffix += 1) id = `${current.id}:text:${suffix}`;
    parts.unshift({ id, type: "text", state: "ready", format: "plain", text: current.content });
  }
  return { ...previous, ...current, parts };
}
