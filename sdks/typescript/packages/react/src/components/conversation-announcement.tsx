"use client";

import React, { useEffect, useRef, useState } from "react";
import type { AgentContentPart, AgentConversationItem, AgentConversationTurn, AgentMessage } from "@zebra-agent/ui-contracts";

export function AgentConversationAnnouncement({ turns, scrollKey }: {
  turns: readonly { turn: AgentConversationTurn; items: readonly AgentConversationItem[] }[];
  scrollKey?: string | undefined;
}) {
  const scope = useRef<{
    key: string | undefined;
    initialized: boolean;
    waiting: boolean;
    seen: Map<string, { message: AgentMessage; content: string; parts: AgentMessage["parts"]; text: string }>;
  } | undefined>(undefined);
  const pending = useRef(new Map<string, string>());
  const previousTurns = useRef(turns);
  const retainedSnapshot = useRef<typeof turns | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [announcement, setAnnouncement] = useState("");
  useEffect(() => {
    if (!scope.current || scope.current.key !== scrollKey) {
      retainedSnapshot.current = scope.current ? previousTurns.current : undefined;
      clearTimeout(timer.current);
      timer.current = undefined;
      pending.current.clear();
      scope.current = { key: scrollKey, initialized: false, waiting: false, seen: new Map() };
      setAnnouncement("");
    }
    previousTurns.current = turns;
    if (!turns.length) retainedSnapshot.current = undefined;
    const retained = retainedSnapshot.current;
    // Wait for new history when navigation temporarily retains the old conversation's snapshot.
    const retainsHistory = !scope.current.initialized && retained?.length && retained.length <= turns.length &&
      retained.every(({ turn, items }, index) => {
        const current = turns[index];
        return current?.turn.id === turn.id && current.turn.userMessage?.id === turn.userMessage?.id &&
          current.turn.userMessage?.content === turn.userMessage?.content && items.length <= current.items.length &&
          items.every((before, itemIndex) => {
            const item = current.items[itemIndex];
            if (item?.kind !== before.kind || item.id !== before.id) return false;
            if (item.kind !== "message" || before.kind !== "message") return true;
            return item.message === before.message || (item.message.id === before.message.id &&
              item.message.status === before.message.status && item.message.content === before.message.content &&
              messageAnnouncement(item.message, item.message.parts) === messageAnnouncement(before.message, before.message.parts));
          });
      });
    const sameSnapshot = retainsHistory && retained.length === turns.length &&
      retained.every(({ items }, index) => items.length === turns[index]?.items.length);
    // ponytail: additions after retained history are live; clear turns on key changes for incremental history loading.
    const baseline = !scope.current.initialized && !(scope.current.waiting && retainsHistory && !sameSnapshot);
    scope.current.waiting = Boolean(sameSnapshot);
    if (baseline && !sameSnapshot) scope.current.seen.clear();
    // A new conversation's first nonempty snapshot is history, including after an empty loading state.
    if (turns.length && !sameSnapshot) { scope.current.initialized = true; retainedSnapshot.current = undefined; }
    for (const { turn, items } of turns) {
      for (const item of items) {
        if (item.kind !== "message" || item.message.status !== "complete") continue;
        const id = JSON.stringify([turn.id, item.message.id]);
        const previous = scope.current.seen.get(id);
        if (previous?.message === item.message) continue;
        const parts = item.message.parts;
        if (previous && previous.content === item.message.content && sameAnnouncementParts(previous.parts, parts)) {
          previous.message = item.message;
          previous.parts = parts;
          continue;
        }
        const text = messageAnnouncement(item.message, parts);
        scope.current.seen.set(id, { message: item.message, content: item.message.content, parts, text });
        if (!baseline && text !== previous?.text) {
          if (text) pending.current.set(id, text);
          else { pending.current.delete(id); setAnnouncement(""); }
        }
      }
    }
    if (!pending.current.size || timer.current !== undefined) return;
    setAnnouncement("");
    // Keep pending completions through token renders and omissions; different IDs with identical text still announce.
    timer.current = setTimeout(() => {
      timer.current = undefined;
      setAnnouncement([...pending.current.values()].join("\n"));
      pending.current.clear();
    }, 0);
  }, [scrollKey, turns]);
  useEffect(() => () => {
    clearTimeout(timer.current);
    timer.current = undefined;
    pending.current.clear();
  }, []);
  return <span className="zebra-agent-turn__announcement" aria-live="polite" aria-atomic="true">{announcement}</span>;
}

function messageAnnouncement(message: AgentMessage, parts: AgentMessage["parts"]) {
  return parts?.length ? parts.filter((part) => part.state === "ready").map(partAnnouncement).join("\n") : message.content;
}

function sameAnnouncementParts(previous: AgentMessage["parts"], current: AgentMessage["parts"]) {
  return previous === current || Boolean(previous && current && previous.length === current.length &&
    previous.every((part, index) => {
      const next = current[index];
      return part === next || (part.type === next?.type && part.state === next.state &&
        (part.state !== "ready" || partAnnouncement(part) === partAnnouncement(next)));
    }));
}

function partAnnouncement(part: AgentContentPart) {
  if (part.type === "text") return part.text;
  if (part.type === "image") return part.alt;
  if (part.type === "file") return part.name;
  return part.title;
}
