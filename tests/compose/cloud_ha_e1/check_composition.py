"""Offline check of the actual native Bundle gateway and trusted E1 counter."""

import argparse
import json
import os
from types import SimpleNamespace

import httpx
from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_integrations.bundle_model import BundleModelGateway
from e1_composition import compose, counter_for
from metering import encode
from zebra_agent_worker.worker_budget import TaskBudgetGate

parser = argparse.ArgumentParser()
parser.add_argument("assembly")
args = parser.parse_args()
with open(args.assembly) as stream:
    assembly = RuntimeAssembly.model_validate_json(stream.read())
assert os.environ.setdefault("ZEBRA_E2E_MODEL_API_KEY", "synthetic-only") == "synthetic-only"
model = BundleModelGateway(assembly)
model.model_request_budget = counter_for(model, assembly)
assert TaskBudgetGate.ready(model)
body = encode({"model": "deepseek-v4-pro", "max_tokens": 1024, "messages": []})
proof = model.model_request_budget(body)
assert proof.exact_body == body and proof.input_upper_bound == len(body)
assert proof.output_cap == assembly.bundle.manifest.domains.model.parameters.max_output_tokens
assert counter_for(model, None) is None
model._api_key = "unapproved"
assert counter_for(model, assembly) is None
model._api_key = "synthetic-only"
with httpx.Client() as client:
    model._client = client
    assert counter_for(model, assembly) is None
settings = SimpleNamespace(deployment="cloud", storage_authority="postgresql")
for url, namespace in (("postgresql://127.0.0.1:25432/production", "ha-e1-20261102"),
                       ("postgresql://127.0.0.1:25432/ha_e1", "foreign")):
    try:
        compose(settings, SimpleNamespace(dsn=url, deployment_namespace=namespace))
    except ValueError:
        pass
    else:
        raise AssertionError("operator fixture accepted an unrelated deployment")
print(json.dumps({"native_budget_ready": True, "offline_only": True,
                  "wrong_key_client_namespace_database_rejected": True}))
