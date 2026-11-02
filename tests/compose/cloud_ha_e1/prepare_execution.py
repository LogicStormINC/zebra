"""Create private, exact synthetic approvals; no DB mutation or publication."""

import argparse
import hashlib
import json
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from agent_core.domain.agent_definition_drafts import AgentDefinitionDraft
from agent_core.domain.runtime_assembly import (
    TEXT_OUTPUT_SCHEMA_DIGEST,
    RuntimeAssembly,
    canonical_budget_profile_digest,
    canonical_provider_profile_digest,
)
from agent_core.domain.runtime_bundle_json import json_digest
from prepare import private
from zebra_agent_api.publication_config import PublicationApproval
from zebra_agent_config import load_settings
from zebra_agent_config.bundle_settings import RuntimeExecutionCatalog, baseline_digest

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
parser.add_argument("--image-digest", required=True)
parser.add_argument("--evidence-digest", required=True)
parser.add_argument("--trust-revision", type=int, default=1)
args = parser.parse_args()
assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", v) for v in (
    args.image_digest, args.evidence_digest
))
assert 1 <= args.trust_revision < 2**53
settings = load_settings()
address = urlsplit(settings.database_url)
assert settings.deployment == "cloud"
assert (address.hostname, address.port, address.path) == ("127.0.0.1", 25432, "/ha_e1")
assert os.environ.get("ZEBRA_DEPLOYMENT_NAMESPACE") == "ha-e1-20261102"
out = args.directory.resolve()
out.mkdir(mode=0o700, parents=False, exist_ok=False)
key, token = secrets.token_hex(32), "rtpub_" + secrets.token_urlsafe(32)
assert re.fullmatch(r"rtpub_[A-Za-z0-9_-]{43}", token)
envelope = json.loads(Path(__file__).with_name("example-envelope.json").read_text())
m = envelope["manifest"]
scope = dict(authority_issuer="https://127.0.0.1:28444", namespace_id="ha-e1-20261102",
             product_id="ha-e1", environment="test", target_id="ha-e1-native",
             deployment_id="ha-e1-20261102")
m["scope"] = scope
profile = dict(provider="openai-compatible", base_url="https://api.deepseek.com",
               api_key_env="ZEBRA_E2E_MODEL_API_KEY", models=["deepseek-v4-pro"],
               max_context_window_tokens=128000, max_output_tokens=1024)
model = m["domains"]["model"]["parameters"]
provider = {**model["provider_profile"], "digest": canonical_provider_profile_digest(profile)}
profile["pin"] = provider
budget = dict(max_model_tokens=200000, max_tool_calls=10, max_runtime_seconds=120)
budget_pin = {**m["domains"]["budget"]["parameters"]["budget_profile"],
              "digest": canonical_budget_profile_digest(budget)}
budget["pin"] = budget_pin
baseline = {**m["baseline_config"], "digest": baseline_digest(settings, key)}
image = {**m["engine"]["image"], "digest": args.image_digest}
evidence = {**m["build_evidence"][0], "digest": args.evidence_digest}
output = {**m["domains"]["instructions"]["parameters"]["output_schema"],
          "digest": TEXT_OUTPUT_SCHEMA_DIGEST}
replacements = {(pin["kind"], pin["id"]): pin for pin in (
    provider, budget_pin, baseline, image, evidence, output
)}
m["baseline_config"], m["engine"]["image"], m["build_evidence"] = baseline, image, [evidence]
model.update(provider_profile=provider, model="deepseek-v4-pro", context_window_tokens=128000,
             max_output_tokens=1024, max_retries=0, temperature_milli=0, thinking="auto")
m["domains"]["instructions"]["parameters"].update(
    output_schema=output, system_text="Synthetic E1. Use pwd only; do not modify files.",
    business_text="No real provider or task quality qualification.", locale="zh-CN",
)
m["domains"]["budget"]["parameters"].update(
    budget_profile=budget_pin, model_tokens=200000, tool_calls=10, runtime_seconds=120
)
m["lock"] = [replacements.get((p["kind"], p["id"]), p) for p in m["lock"]]
envelope["bundle_digest"] = json_digest(m)
assembly = RuntimeAssembly.model_validate_json(json.dumps(dict(
    bundle=envelope, provider_profile=profile, budget_profile=budget
)))
catalog = dict(schema_version="cloud-agent.execution-catalog/1", scope=scope, image=image,
               baseline_config=baseline, baseline_key=key, providers=[profile], budget=budget,
               output_schema=output, build_evidence=[evidence])
assert RuntimeExecutionCatalog.model_validate_json(json.dumps(catalog)).resolve(
    assembly.bundle
) == assembly
refs = {name + "_ref": f"e1/{name}@1" for name in (
    "model_policy", "tool_profile", "memory_policy", "security_policy",
    "evaluation_profile", "runtime_profile"
)}
skills = hashlib.sha256(b"[]").hexdigest()
definition = str(uuid4())
approval = dict(
    schema_version="cloud-agent.publication-approval/1", scope=scope, audience="ha-e1-management",
    actor="ha-e1-publisher", definition_id=definition, trust_revision=args.trust_revision,
    credential_sha256=hashlib.sha256(token.encode()).hexdigest(),
    expires_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
    actions=["materialize", "publish", "read"],
    references=[*refs.values(), skills, "runtime-bundle/" + envelope["bundle_digest"][7:] + "@1"],
    template=dict(name="E1 synthetic byte-meter", description="Isolated native transport test",
                  skill_snapshot_digest=skills, **refs),
    evaluator_actors=["ha-e1-native-meter-evaluator"], consumer_hosts=["ha-e1"],
    policy_version="e1-meter-wire/1",
)
PublicationApproval.model_validate_json(json.dumps(approval))
AgentDefinitionDraft(
    definition_id=UUID(definition), authority_issuer=scope["authority_issuer"],
    namespace_id=scope["namespace_id"], updated_at=datetime.now(UTC), **approval["template"],
)
for name, value in (("catalog.json", catalog), ("publication.json", approval),
                    ("bundle.json", envelope), ("assembly.json", assembly.model_dump(mode="json"))):
    private(out / name, json.dumps(value, indent=2))
private(out / "publication-token", token)
print(json.dumps({"prepared": True, "definition_id": definition,
                  "bundle_digest": envelope["bundle_digest"], "output_cap": 1024}))
