"""Read-only pre-change container inventories for the two explicit preparation paths."""

import json


def record_production_inventory(root, capture, private):
    before = {}
    for name in [
        "erpnext-backend-1",
        "erpnext-frontend-1",
        "erpnext-agent-api-1",
        "erpnext-agent-chat-worker-1",
        "zebra-web-search-searxng-1",
        "zebra-yahoo-egress",
    ]:
        data = json.loads(capture("docker", "inspect", name))[0]
        before[name] = dict(
            id=data["Id"],
            image=data["Image"],
            started=data["State"]["StartedAt"],
            restarts=data["RestartCount"],
        )
        if name in {"erpnext-backend-1", "erpnext-frontend-1"}:
            private(root / (name + ".inspect.json"), json.dumps(data))
    private(root / "before.json", json.dumps(before, indent=2))


def record_qa_inventory(root, capture, write):
    before = {}
    for name in [
        "erpnext-agent-api-1",
        "erpnext-agent-chat-worker-1",
        "erpnext-backend-1",
        "zebra-web-search-searxng-1",
        "zebra-yahoo-egress",
    ]:
        item = json.loads(capture("docker", "inspect", name))[0]
        before[name] = dict(
            id=item["Id"],
            image=item["Image"],
            started=item["State"]["StartedAt"],
            restarts=item["RestartCount"],
        )
    write(root / "before.json", json.dumps(before, indent=2))
