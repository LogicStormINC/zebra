"""Bounded projection of public Task events. No private model/tool payloads."""

import hashlib
import json
import re
from urllib.parse import urlsplit


def public_parts(value):
    """Keep only inert text and owned artifact coordinates from public delivery."""
    result = []
    for part in value[:16] if isinstance(value, list) else []:
        if not isinstance(part, dict) or not isinstance(part.get("id"), str):
            continue
        kind = part.get("type")
        base = dict(
            id=part["id"][:200],
            state=part.get("state")
            if part.get("state") in {"ready", "processing", "failed"}
            else "ready",
            type=kind,
        )
        if kind == "text" and isinstance(part.get("text"), str):
            result.append(
                dict(
                    base,
                    format="markdown" if part.get("format") == "markdown" else "plain",
                    text=part["text"][:100000],
                )
            )
        elif kind in {"external_video", "external-video"}:
            url = part.get("sourceUrl") or part.get("url")
            try:
                parsed = urlsplit(url) if isinstance(url, str) and len(url) <= 2048 else None
                providers = {
                    "youtube.com": "youtube",
                    "www.youtube.com": "youtube",
                    "youtu.be": "youtube",
                    "bilibili.com": "bilibili",
                    "www.bilibili.com": "bilibili",
                    "vimeo.com": "vimeo",
                    "www.vimeo.com": "vimeo",
                    "player.vimeo.com": "vimeo",
                }
                if (
                    parsed
                    and parsed.scheme == "https"
                    and not parsed.username
                    and not parsed.password
                    and parsed.port in {None, 443}
                    and parsed.hostname in providers
                ):
                    result.append(
                        dict(
                            base,
                            type="external-video",
                            provider=providers[parsed.hostname],
                            url=url,
                            title=str(part.get("title", "视频"))[:255],
                        )
                    )
            except ValueError:
                pass
        elif (
            kind == "chart"
            and part.get("specType") == "vega-lite"
            and str(part.get("specVersion", "")).startswith("6")
        ):
            base.update(
                specType="vega-lite",
                specVersion="6",
                title=str(part.get("title", "图表"))[:255],
                description=str(part.get("description", ""))[:500],
            )
            for key in (
                "specArtifactId",
                "dataArtifactId",
                "fallbackImageArtifactId",
                "fallbackTableArtifactId",
            ):
                if isinstance(part.get(key), str) and re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", part[key]
                ):
                    base[key] = part[key]
            if isinstance(part.get("spec"), dict) and len(json.dumps(part["spec"])) <= 32768:
                base["spec"] = part[
                    "spec"
                ]  # the shared chart renderer rejects URLs and executable expressions
            result.append(base)
        elif kind in {"file", "image", "video"} and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", str(part.get("artifactId", ""))
        ):
            media = part.get("mimeType")
            if not isinstance(media, str) or not re.fullmatch(r"[\w.+-]+/[\w.+-]+", media):
                continue
            base.update(artifactId=part["artifactId"], mimeType=media)
            for key in ("name", "fileName", "alt", "title", "description"):
                if isinstance(part.get(key), str):
                    base[key] = part[key][:500]
            if type(part.get("sizeBytes")) is int and 0 <= part["sizeBytes"] <= 2**53 - 1:
                base["sizeBytes"] = part["sizeBytes"]
            result.append(base)
    return result


def digest(message):
    return hashlib.sha256(
        json.dumps(
            {key: message[key] for key in ("id", "content", "parts", "sources") if key in message},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def body_text(message):
    text = [part["text"] for part in message.get("parts", []) if part.get("type") == "text"]
    return re.sub(
        r"artifact://[^\s)\]<>]+",
        "（成果见文件区）",
        "\n\n".join(text) if text else message["content"],
    )


def parts_truncated(value):
    return isinstance(value, list) and (
        len(value) > 16
        or any(
            isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
            and len(part["text"]) > 100000
            for part in value
        )
    )


def messages(events):
    result = []
    parts = []
    truncated = False
    for index, item in enumerate(events[-2000:]):
        event = item.get("event", item)
        kind = str(event.get("type", event.get("event_type", ""))).upper()
        data = event.get("payload", event.get("data", {}))
        if not isinstance(data, dict):
            continue
        if kind == "TOOL_EXECUTION_COMPLETED":
            metadata = data.get("metadata") or {}
            if isinstance(metadata, dict) and metadata.get("delivery") is True:
                raw_parts = metadata.get("content_parts")
                rich = public_parts(raw_parts)
                if (
                    not rich
                    and isinstance(metadata.get("artifact_uri"), str)
                    and metadata["artifact_uri"].startswith("artifact://")
                ):
                    mime = metadata.get("mime_type") or ""
                    rich = public_parts(
                        [
                            dict(
                                id="delivery:" + str(index),
                                type="image"
                                if mime.startswith("image/")
                                else "video"
                                if mime.startswith("video/")
                                else "file",
                                artifactId=metadata["artifact_uri"][11:],
                                mimeType=mime,
                                fileName=metadata.get("file_name"),
                                name=metadata.get("file_name"),
                                sizeBytes=metadata.get("size_bytes"),
                            )
                        ]
                    )
                truncated = truncated or parts_truncated(raw_parts) or len(parts) + len(rich) > 16
                parts = (parts + rich)[:16]
        role = content = None
        if kind in {"TASK_PREPARED", "SESSION_CREATED"}:
            role, content = "user", data.get("prompt") or data.get("objective")
        elif kind in {
            "USER_MESSAGE_ADDED",
            "TASK_MESSAGE_APPENDED",
            "USER_MESSAGE_RECEIVED",
            "CLARIFICATION_RESPONDED",
        }:
            role, content = "user", data.get("content") or data.get("message")
            parts, truncated = [], False
        elif kind == "CLARIFICATION_REQUESTED":
            role, content = "assistant", data.get("question")
        elif kind in {
            "ANSWER_COMMITTED",
            "ASSISTANT_MESSAGE_COMMITTED",
            "ASSISTANT_MESSAGE_CREATED",
        }:
            role, content = "assistant", data.get("assistant_message") or data.get("content") or ""
        raw_parts = data.get("parts") or data.get("content_parts")
        rich = (
            public_parts(raw_parts)
            if role == "assistant" and kind != "CLARIFICATION_REQUESTED"
            else []
        )
        if isinstance(content, str) and (content or role == "assistant" and (rich or parts)):
            message = dict(
                id=str(event.get("event_id") or item.get("event_id", index)),
                role=role,
                content=content[:100000],
            )
            if role == "user":
                message["attachments"] = []
                for ref in (
                    data.get("attachments", [])[:4]
                    if isinstance(data.get("attachments"), list)
                    else []
                ):
                    if not isinstance(ref, dict) or ref.get("message_event_id") != message["id"]:
                        continue
                    message["attachments"].append(
                        {
                            key: ref[key]
                            for key in (
                                "attachment_id",
                                "file_name",
                                "media_type",
                                "size_bytes",
                                "original_size_bytes",
                            )
                            if isinstance(ref.get(key), str) or type(ref.get(key)) is int
                        }
                    )
            elif kind != "CLARIFICATION_REQUESTED":
                rich = rich or parts
                if rich:
                    message["parts"] = rich
                message["sources"] = []
                for source in (
                    data.get("sources", [])[:20] if isinstance(data.get("sources"), list) else []
                ):
                    if (
                        not isinstance(source, dict)
                        or not isinstance(source.get("url"), str)
                        or len(source["url"]) > 2048
                    ):
                        continue
                    try:
                        url = urlsplit(source["url"])
                        if (
                            url.scheme == "https"
                            and url.hostname
                            and not url.username
                            and not url.password
                        ):
                            message["sources"].append(
                                dict(
                                    title=str(
                                        source.get("title") or source.get("label") or url.hostname
                                    )[:255],
                                    url=source["url"],
                                )
                            )
                    except ValueError:
                        pass
                message["content_truncated"] = (
                    len(content) > 100000 or parts_truncated(raw_parts) or truncated
                )
                message["digest"] = digest(message)
                parts, truncated = [], False
            result.append(message)
    return result[-100:]


def load(doc):
    """Read the same finite public prefix for the UI and answer mutations."""
    from zebra_erpnext import cloud

    if not doc.task_id:
        return {}, []
    header = cloud.request(doc, "GET", f"/tasks/{doc.task_id}/header", run_id=doc.active_run_id)
    response = cloud.request(
        doc,
        "GET",
        f"/tasks/{doc.task_id}/stream",
        run_id=doc.active_run_id,
        stream=True,
        params={"recovery": "full"},
    )
    return header, read_events(response, header.get("current_sequence", 0))


def read_events(response, highwater):
    """Read the finite recovery prefix of the native SSE; never tail in a snapshot."""
    import json
    from collections import deque

    events, size = deque(maxlen=2000), 0
    try:
        for line in response.iter_lines(chunk_size=1):
            size += len(line)
            if size > 4 * 1024 * 1024:
                raise ValueError("Conversation history exceeds the bounded snapshot size")
            if line.startswith(b":"):
                continue
            if not line.startswith(b"data: "):
                continue
            event = json.loads(line[6:])
            if event.get("name") == "zebra.stream.recovery_complete":
                break
            if "event_type" in event:
                events.append(event)
                if event.get("sequence", -1) >= highwater:
                    break
        return list(events)
    finally:
        response.close()


def public_state(header, events=(), *, pending_command=False):
    """Project only public status and the active clarification, never tool context."""
    status = header.get("current_turn_status") or header.get("status") or "idle"
    states = {
        "running": "running",
        "queued": "queued",
        "dispatching": "submitting",
        "accepted": "accepted",
        "created": "accepted",
        "ready": "accepted",
        "waiting_input": "waiting_for_user",
        "awaiting_input": "waiting_for_user",
        "awaiting_approval": "waiting_for_user",
        "waiting_approval": "waiting_for_user",
        "waiting_client_effect": "waiting_for_user",
        "suspended": "paused",
        "paused": "paused",
    }
    outcome = {
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "stopped": "cancelled",
        "blocked": "blocked",
        "partial": "partial",
    }.get(status)
    state = {"phase": "terminal" if outcome else states.get(status, "idle"), "availableActions": []}
    if outcome:
        state["outcome"] = outcome
    if pending_command and status in {"created", "ready", "accepted"}:
        state.update(phase="reconciling", safeMessage="提交结果正在核对，请重新连接查看已有任务")
    position = header.get("queue_position")
    if state["phase"] == "queued" and type(position) is int and position >= 0:
        state["queuePosition"] = position
    active = header.get("clarification_context") or {}
    active_id = active.get("clarification_id") if isinstance(active, dict) else None
    clarification = None
    if state["phase"] == "waiting_for_user" and isinstance(active_id, str):
        for item in reversed(events):
            event = item.get("event", item)
            kind = str(event.get("type", event.get("event_type", ""))).upper()
            data = event.get("payload", event.get("data", {}))
            if (
                kind == "CLARIFICATION_REQUESTED"
                and isinstance(data, dict)
                and data.get("clarification_id") == active_id
            ):
                question = data.get("question")
                if isinstance(question, str) and question:
                    choices = data.get("choices", [])
                    clarification = {
                        "clarification_id": active_id[:200],
                        "question": question[:8000],
                        "choices": [value[:500] for value in choices[:30] if isinstance(value, str)]
                        if isinstance(choices, list)
                        else [],
                    }
                break
    command_outcome = header.get("command_outcome") or {}
    if command_outcome.get("code") in {
        "erp_fresh_authority_refused",
        "erp_fresh_authority_unavailable",
        "erp_fresh_authority_retry_exhausted",
    }:
        scheduled = command_outcome.get("retry_scheduled") is True
        state = {
            "phase": "reconciling" if scheduled else "terminal",
            "availableActions": [],
            "safeMessage": "权限服务暂时不可用，正在等待有限重试"
            if scheduled
            else "本次请求尚未执行，请重新验证权限后继续原请求",
        }
        if not scheduled:
            state["outcome"] = "blocked"
            if command_outcome.get("retry_eligible") is True and not pending_command:
                state["availableActions"] = ["retry"]
        return {
            "status": "waiting" if scheduled else "blocked",
            "canonical_status": status,
            "run_state": state,
            "clarification": None,
            "command_outcome": command_outcome,
        }
    return {"status": status, "run_state": state, "clarification": clarification}
