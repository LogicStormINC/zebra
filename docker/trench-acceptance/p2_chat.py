#!/usr/bin/env python3
"""P2 end-to-end product chat: Trench strategy chat -> Zebra -> streamed answer.

Drives the real product API on the acceptance server the same way the
toc-frontend strategy workspace does.
"""
import json
import os
import ssl
import sys
import time
import urllib.request

BASE = os.getenv("TRENCH_BASE_URL", "http://127.0.0.1:18000").rstrip("/")
CTX = ssl.create_default_context()


def call(method, path, payload=None, headers=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        return e.code, {"error": body}


def main():
    cookie = open("/tmp/trench_cookie.txt").read().strip()
    headers = {"Cookie": cookie}

    status, me = call("GET", "/api/trench-ai/me", headers=headers)
    print("me:", status)
    if status != 200:
        print(me)
        return 1

    stamp = int(time.time())
    status, conv = call(
        "POST",
        "/api/trench-ai/conversations",
        {"title": f"Zebra 对接验收 {stamp}"},
        headers=headers,
    )
    print("conversation:", status, json.dumps(conv, ensure_ascii=False)[:160])
    key = None
    if isinstance(conv, dict):
        data = conv.get("data") or {}
        key = (data.get("conversation") or {}).get("conversation_key") or data.get(
            "conversation_key"
        )
    if not key:
        print("no conversation key; abort")
        return 1

    body = {
        "auto_select_skills": True,
        "conversation_key": key,
        "market": "A股",
        "message": "你是谁？你能帮我做什么？",
    }
    req = urllib.request.Request(
        BASE + "/api/trench-ai/chat/stream",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream", **headers},
    )
    print("=== product chat SSE ===")
    deltas, events = [], []
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            print("status:", r.status)
            for raw in r:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:])
                except ValueError:
                    continue
                kind = ev.get("type") or ev.get("event") or ""
                events.append(kind)
                if kind in ("delta", "agent_step", "done", "error", "meta"):
                    if kind == "delta":
                        deltas.append(
                            ev.get("answer") or ev.get("delta") or ev.get("content") or ""
                        )
                    elif kind == "error":
                        print("error event:", json.dumps(ev, ensure_ascii=False)[:300])
    except Exception as exc:
        print("stream exception:", exc)
    from collections import Counter

    print("events:", dict(Counter(events)))
    print("=== assistant answer ===")
    print("".join(deltas)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
