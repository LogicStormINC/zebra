"""Run: python3 tests/test_frontend_profile_checks.py [--ssh ubuntu@HOST].
Optional native validation loads pure source in memory: no DB, publication or configuration writes.
"""

import argparse
import base64
import json
import math
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
definition = __import__("frontend_profile", fromlist=("definition",)).definition
install_profile = __import__("frontend_profile", fromlist=("install_profile",)).install_profile
validate_patch_cell_budget = __import__(
    "frontend_profile", fromlist=("validate_patch_cell_budget",)
).validate_patch_cell_budget


def rejects(fn, phrase):
    try:
        fn()
    except ValueError as exc:
        assert phrase in str(exc)
    else:
        raise AssertionError("Expected rejection: " + phrase)


v1, v2 = definition(1), definition(2)
assert [action["name"] for action in v1["actions"]] == [
    "erpnext.ui.document.open",
    "erpnext.ui.form.fill",
]
assert v1["actions"][1]["parameters"]["properties"]["values"] == {"type": "object"}
assert v1["readables"] == [{"name": "erpnext.ui.context"}]
assert len(v2["actions"]) == 7
assert {action["risk"] for action in v2["actions"]} == {"presentation", "navigation", "local_state"}
assert all(action["max_result_bytes"] == 16384 for action in v2["actions"])
assert v2["actions"][0]["parameters"] != v1["actions"][0]["parameters"]
assert definition(2) == v2
v2["actions"][0]["parameters"]["properties"]["doctype"]["maxLength"] = 999
assert definition(2)["actions"][0]["parameters"]["properties"]["doctype"]["maxLength"] == 140
v2 = definition(2)
rejects(lambda: definition(True), "revisions")
rejects(lambda: definition(3), "revisions")

ALLOWED = {
    "enum",
    "maxItems",
    "maxLength",
    "additionalProperties",
    "items",
    "required",
    "maximum",
    "minItems",
    "minLength",
    "properties",
    "minimum",
    "description",
    "type",
}


def check_schema(schema, depth=0):
    assert depth <= 4 and set(schema) <= ALLOWED
    assert len(json.dumps(schema)) <= 8192
    kind = schema["type"]
    if kind == "object":
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) <= schema["properties"].keys()
        for child in schema["properties"].values():
            check_schema(child, depth + 1)
    elif kind == "array":
        assert 0 <= schema["minItems"] <= schema["maxItems"] <= 1000
        check_schema(schema["items"], depth + 1)
    elif kind == "string" and "enum" not in schema:
        assert 0 <= schema["minLength"] <= schema["maxLength"] <= 10000
    else:
        assert kind in {"string", "boolean", "number", "integer"}


for action in v2["actions"]:
    check_schema(action["parameters"])
    check_schema(action["result_schema"])
check_schema(v2["readables"][0]["state_schema"])

# Samples below use the local structural checker. --ssh validates native profile
# definitions/publish gates, not payload instances.
samples = {
    "erpnext.ui.document.open": {
        "expected": {"route": ["List", "ToDo", "List"]},
        "doctype": "ToDo",
        "name": "TODO-1",
    },
    "erpnext.ui.list.open": {
        "expected": {"route": ["Workspaces"]},
        "doctype": "ToDo",
        "filters": [{"field": "status", "operator": "=", "kind": "text", "text": "Open"}],
    },
    "erpnext.ui.report.open": {
        "expected": {"route": ["Workspaces"]},
        "report": "General Ledger",
        "filters": [{"field": "company", "kind": "text", "text": "QA"}],
    },
    "erpnext.ui.document.new": {"expected": {"route": ["Workspaces"]}, "doctype": "ToDo"},
    "erpnext.ui.page.read": {
        "expected": {"route": ["Form", "ToDo", "TODO-1"]},
        "fields": ["description"],
    },
    "erpnext.ui.form.fill": {
        "expected": {
            "route": ["Form", "ToDo", "TODO-1"],
            "doctype": "ToDo",
            "name": "TODO-1",
            "modified": "",
            "draft_digest": "a" * 64,
        },
        "values": [{"field": "description", "kind": "text", "text": "QA"}],
    },
    "erpnext.ui.form.children.patch": {
        "expected": {
            "route": ["Form", "ToDo", "TODO-1"],
            "doctype": "ToDo",
            "name": "TODO-1",
            "modified": "",
            "draft_digest": "a" * 64,
        },
        "field": "items",
        "updates": [{"name": "ROW-1", "field": "qty", "kind": "number", "number": 1}],
        "append": [{"row_key": "new-1", "field": "qty", "kind": "number", "number": 2}],
    },
}


def validate_sample(schema, value):
    kind = schema["type"]
    types = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
    }
    if (
        not isinstance(value, types[kind])
        or kind in {"number", "integer"}
        and (isinstance(value, bool) or not math.isfinite(value))
    ):
        raise ValueError("type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("enum")
    if kind == "object":
        if value.keys() - schema["properties"].keys() or set(schema["required"]) - value.keys():
            raise ValueError("fields")
        for key, child in value.items():
            validate_sample(schema["properties"][key], child)
    if kind == "array":
        if not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise ValueError("length")
        for child in value:
            validate_sample(schema["items"], child)
    if (
        kind == "string"
        and not schema.get("enum")
        and not schema["minLength"] <= len(value) <= schema["maxLength"]
    ):
        raise ValueError("length")
    if kind in {"number", "integer"} and (
        value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf)
    ):
        raise ValueError("bounds")


for action in v2["actions"]:
    sample = samples[action["name"]]
    validate_sample(action["parameters"], sample)
    rejects(
        lambda *, action=action, sample=sample: validate_sample(
            action[("parameters")], dict(sample, arbitrary_rpc=("bad"))
        ),
        ("fields"),
    )
fill = next(a["parameters"] for a in v2["actions"] if a["name"].endswith("form.fill"))
fill_sample = samples["erpnext.ui.form.fill"]
rejects(lambda: validate_sample(fill, dict(fill_sample, values=[])), "length")
rejects(
    lambda: validate_sample(
        fill, dict(fill_sample, values=[{"field": "qty", "kind": "number", "number": float("nan")}])
    ),
    "type",
)
rejects(
    lambda: validate_sample(
        fill, dict(fill_sample, values=[{"field": "qty", "kind": "number", "number": True}])
    ),
    "type",
)
rejects(
    lambda: validate_sample(
        fill, dict(fill_sample, values=[{"field": "qty", "kind": "text", "text": "a" * 10001}])
    ),
    "length",
)


patch = next(a for a in v2["actions"] if a["name"].endswith("form.children.patch"))
assert patch["parameters"]["properties"]["updates"]["maxItems"] == 100
assert patch["parameters"]["properties"]["append"]["maxItems"] == 100
validate_patch_cell_budget({"updates": [None] * 50, "append": [None] * 50})
rejects(
    lambda: validate_patch_cell_budget({"updates": [None] * 50, "append": [None] * 51}), "100 total"
)
assert "COMPLETE serialized result" in patch["description"]
list_result = next(a for a in v2["actions"] if a["name"].endswith("list.open"))["result_schema"]
validate_sample(
    list_result,
    {
        "context": {"route": ["List", "ToDo", "List"]},
        "opened": True,
        "state": "loaded",
        "complete": False,
    },
)
rejects(
    lambda: validate_sample(
        list_result,
        {
            "context": {"route": ["List", "ToDo", "List"]},
            "opened": True,
            "state": "loaded",
            "complete": True,
        },
    ),
    "enum",
)

calls = []


class Registry:
    published = None
    binding = None

    def get_profile(self, app, revision):
        return self.published


class Service:
    def get_binding_for_host(self, **kwargs):
        return registry.binding

    def publish(self, profile):
        calls.append(("publish", profile))
        registry.published = profile

    def bind(self, **kwargs):
        calls.append(("bind", kwargs))


registry, service = Registry(), Service()
profile = SimpleNamespace(revision=2, profile_digest="digest2")
registry.binding = SimpleNamespace(revision=1, profile_digest="digest1", binding_revision=7)
rejects(lambda: install_profile(service, registry, profile), "deliberately")
assert not calls and registry.published is None
install_profile(service, registry, profile, rebind=True)
assert [call[0] for call in calls] == ["publish", "bind"]
assert calls[-1][1]["expected_binding_revision"] == 7
calls.clear()
registry.binding = SimpleNamespace(revision=2, profile_digest="digest2", binding_revision=8)
install_profile(service, registry, profile)
assert not calls
registry.published = SimpleNamespace(revision=2, profile_digest="different")
rejects(lambda: install_profile(service, registry, profile), "different content")
assert not calls
registry.published = registry.binding = None
install_profile(service, registry, profile)
assert calls[-1][1]["expected_binding_revision"] == 0
print(
    "PASS pure v1 preservation, seven bounded native-compatible v2 sc"
    "hemas, immutable publication and deliberate CAS rebinding"
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ssh")
options = parser.parse_args()
if options.ssh:
    source = base64.b64encode((ROOT / "deploy/frontend_profile.py").read_bytes()).decode()
    script = (
        "import base64, json\nfrom agent_core.domain.client_capabilities i"
        "mport FrontendCapabilityProfileVersion, canonical_client_capabil"
        "ity_digest, validate_profile_for_publish\nexec(compile(base64.b64"
        "decode(SOURCE), 'frontend_profile.py', 'exec'))\np1 = FrontendCap"
        "abilityProfileVersion.model_validate(definition(1))\np2 = Fronten"
        "dCapabilityProfileVersion.model_validate(definition(2))\nvalidate"
        "_profile_for_publish(p1)\nvalidate_profile_for_publish(p2)\nassert"
        " p1.profile_digest == '281a801786c61aca15c454b62dce90a3522e0354c"
        "cde33ec3303e2e748730fc3'\nassert p1.profile_digest != p2.profile_"
        "digest\nassert len(p2.actions) == 7\nfor action in p2.actions:\n   "
        " assert action.max_result_bytes == 16384\n    assert len(canonica"
        "l_client_capability_digest(action.model_dump(mode='json'))) == 6"
        "4\nprint(json.dumps({'native_profile_validation':'passed','v1_dig"
        "est_unchanged':True,'v2_digest':p2.profile_digest,'v2_actions':l"
        "en(p2.actions),'publication':False}))\n"
    )
    subprocess.run(
        ["ssh", options.ssh, "docker exec -i erpnext-agent-api-1 python -"],
        input="SOURCE = " + repr(source) + "\n" + script,
        text=True,
        check=True,
    )
