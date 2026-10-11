"""Remove exact repeated record text from model input, never from durable evidence."""

import json

from agent_core.domain.messages import MessageRole, SessionMessage


def compact_repeated_records(messages: list[SessionMessage]) -> list[SessionMessage]:
    seen: dict[str, str] = {}
    compacted = []
    for message in messages:
        if message.role is MessageRole.USER:
            seen.clear()
        content = message.content
        if message.role is MessageRole.TOOL and len(content) <= 262_144:
            try:
                payload = json.loads(content)
            except (ValueError, RecursionError):
                payload = None
            if isinstance(payload, dict):
                wrapped = payload.get("status") == "executed" and isinstance(
                    payload.get("output"), str
                )
                try:
                    data = json.loads(payload["output"]) if wrapped else payload
                except (ValueError, RecursionError):
                    data = None
                if (
                    isinstance(data, dict)
                    and data.get("query_completed") is True
                    and data.get("status") == "ready"
                    and isinstance(data.get("items"), list)
                    and len(data["items"]) <= 32
                ):
                    items, changed = [], False
                    for item in data["items"]:
                        if not isinstance(item, dict) or not all(
                            isinstance(item.get(key), str) and item[key]
                            for key in ("event_id", "source_id", "period_id")
                        ):
                            items.append(item)
                            continue
                        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                        if key in seen:
                            reference = {k: item[k] for k in (
                                "event_id", "source_id", "period_id", "original_url"
                            ) if k in item}
                            reference["same_record_in_tool_call"] = seen[key]
                            # ponytail: only exact duplicates within one user turn;
                            # changed facts and cross-turn freshness are never elided.
                            if len(json.dumps(reference)) < len(key):
                                items.append(reference)
                                changed = True
                                continue
                        seen[key] = message.tool_call_id or str(message.message_id)
                        items.append(item)
                    if changed:
                        data = {**data, "items": items}
                        if wrapped:
                            payload = {**payload, "output": json.dumps(data, ensure_ascii=False)}
                        else:
                            payload = data
                        content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        compacted.append(message if content == message.content else message.model_copy(
            update={"content": content}
        ))
    return compacted
