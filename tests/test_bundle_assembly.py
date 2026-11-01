"""Operator catalog and baseline trust boundaries; no remote asset resolution."""

from dataclasses import replace

import pytest
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_config.bundle_settings import baseline_digest


def settings():
    return ZebraAgentSettings(
        profile="test",
        database_url="private-dsn",
        api=ApiSettings(auth_token="private-token"),
        model=ModelSettings(
            provider="test", api_key_env="TEST_KEY", base_url="https://test", model="a"
        ),
    )


def test_baseline_pins_all_nonmodel_configuration_without_exposing_secrets():
    original = settings()
    key = "ab" * 32
    digest = baseline_digest(original, key)
    assert digest.startswith("sha256:") and len(digest) == 71
    assert digest == baseline_digest(
        replace(original, model=replace(original.model, model="new")), key
    )
    assert digest != baseline_digest(replace(original, api=ApiSettings(auth_token="changed")), key)
    assert digest != baseline_digest(replace(original, cloud_extension_worker_enabled=True), key)
    assert digest != baseline_digest(original, "cd" * 32)
    assert "private" not in digest


@pytest.mark.parametrize("key", ["", "ab", "z" * 64, "AB" * 32])
def test_invalid_baseline_key_fails_closed(key):
    with pytest.raises(ValueError):
        baseline_digest(settings(), key)


def approved_assembly(worker_settings, model="alpha"):
    """Build approved artifacts from the published envelope, recomputing every pin."""
    import json
    from pathlib import Path

    from agent_core.domain.runtime_assembly import (
        TEXT_OUTPUT_SCHEMA_DIGEST,
        RuntimeAssembly,
        canonical_budget_profile_digest,
        canonical_provider_profile_digest,
    )
    from agent_core.domain.runtime_bundle import parse_runtime_bundle
    from agent_core.domain.runtime_bundle_json import json_digest

    envelope = json.loads(
        Path("docs/contracts/runtime-bundle-v1/example-envelope.json").read_bytes()
    )
    manifest = envelope["manifest"]
    params = manifest["domains"]["model"]["parameters"]
    profile = dict(
        provider="openai-compatible",
        base_url="https://models.example/v1",
        api_key_env="BUNDLE_MODEL_KEY",
        models=["alpha", "beta"],
        max_context_window_tokens=128000,
        max_output_tokens=4096,
    )
    provider_pin = {
        **params["provider_profile"],
        "digest": canonical_provider_profile_digest(profile),
    }
    profile["pin"] = provider_pin
    baseline = {
        **manifest["baseline_config"],
        "digest": baseline_digest(worker_settings, "ab" * 32),
    }
    output = {
        **manifest["domains"]["instructions"]["parameters"]["output_schema"],
        "digest": TEXT_OUTPUT_SCHEMA_DIGEST,
    }
    budget = dict(max_model_tokens=1_000_000, max_tool_calls=500, max_runtime_seconds=3600)
    budget_pin = {
        **manifest["domains"]["budget"]["parameters"]["budget_profile"],
        "digest": canonical_budget_profile_digest(budget),
    }
    budget["pin"] = budget_pin
    replacements = {
        ("provider-profile", provider_pin["id"]): provider_pin,
        ("baseline-config", baseline["id"]): baseline,
        ("output-schema", output["id"]): output,
        ("budget-profile", budget_pin["id"]): budget_pin,
    }
    manifest["baseline_config"] = baseline
    params.update(
        provider_profile=provider_pin,
        model=model,
        context_window_tokens=128000,
        max_output_tokens=2048,
        max_retries=0,
        temperature_milli=250,
        thinking="auto",
    )
    manifest["domains"]["instructions"]["parameters"].update(
        output_schema=output,
        system_text="Frozen system rules.",
        business_text=f"Frozen business {model}.",
        locale="zh-CN",
    )
    manifest["lock"] = [replacements.get((pin["kind"], pin["id"]), pin) for pin in manifest["lock"]]
    envelope["bundle_digest"] = json_digest(manifest)
    bundle = parse_runtime_bundle(json.dumps(envelope).encode())
    assembly = RuntimeAssembly.model_validate_json(
        json.dumps(dict(bundle=envelope, provider_profile=profile, budget_profile=budget))
    )
    catalog = dict(
        schema_version="cloud-agent.execution-catalog/1",
        scope=manifest["scope"],
        image=manifest["engine"]["image"],
        baseline_config=baseline,
        baseline_key="ab" * 32,
        providers=[profile],
        budget=budget,
        output_schema=output,
        build_evidence=manifest["build_evidence"],
    )
    assert assembly.bundle == bundle
    return assembly, catalog


def write_catalog(tmp_path, worker_settings):
    import json
    from pathlib import Path

    assembly, catalog = approved_assembly(worker_settings)
    path = Path(tmp_path) / "execution-catalog.json"
    path.write_text(json.dumps(catalog))
    path.chmod(0o600)
    return assembly, replace(worker_settings, runtime_bundle_config=str(path)), catalog


def test_approved_catalog_resolves_without_storing_baseline_key(tmp_path):
    from zebra_agent_config.bundle_settings import load_execution_catalog

    assembly, configured, _ = write_catalog(tmp_path, settings())
    catalog = load_execution_catalog(configured.runtime_bundle_config)
    assert catalog.resolve(assembly.bundle) == assembly
    assert "baseline_key" not in catalog.model_dump()
    assert "ab" * 32 not in repr(catalog)
    assert "baseline_key" not in assembly.model_dump_json()


def test_missing_changed_unapproved_or_hostile_catalog_is_refused(tmp_path):
    import json
    from pathlib import Path

    from zebra_agent_api.bundle_assembly import resolve_bundle_assembly
    from zebra_agent_config.bundle_settings import load_execution_catalog

    assembly, configured, catalog = write_catalog(tmp_path, settings())
    payload = assembly.bundle.model_dump(mode="json")
    with pytest.raises(ValueError, match="BUNDLE_ASSEMBLY_REFUSED"):
        resolve_bundle_assembly(payload, None)
    catalog["scope"]["product_id"] = "other-product"
    path = Path(configured.runtime_bundle_config)
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="BUNDLE_ASSEMBLY_REFUSED"):
        resolve_bundle_assembly(payload, str(path))
    for raw in (
        b'{"baseline_key":"private","baseline_key":"other"}',
        b" " * 262145,
        b'{"x":0.1}',
        b'{"x":NaN}',
    ):
        path.write_bytes(raw)
        with pytest.raises(ValueError, match="^INVALID_EXECUTION_CATALOG$"):
            load_execution_catalog(str(path))


def _configurable_budget_envelope(worker_settings, ceilings=None):
    """Example envelope with budget switched to configurable within approval."""
    import json
    from pathlib import Path

    from agent_core.domain.runtime_assembly import canonical_budget_profile_digest
    from agent_core.domain.runtime_bundle import parse_runtime_bundle
    from agent_core.domain.runtime_bundle_json import json_digest

    assembly, catalog = approved_assembly(settings())
    envelope = json.loads(
        Path("docs/contracts/runtime-bundle-v1/example-envelope.json").read_bytes()
    )
    manifest = envelope["manifest"]
    # 复用 approved_assembly 的既有替换（provider/baseline/output）再补 budget。
    approved = assembly.bundle.manifest.model_dump(mode="json")
    manifest.update(
        baseline_config=approved["baseline_config"],
        lock=approved["lock"],
    )
    manifest["domains"]["model"]["parameters"] = approved["domains"]["model"]["parameters"]
    manifest["domains"]["instructions"]["parameters"] = approved["domains"]["instructions"][
        "parameters"
    ]
    profile = dict(catalog["budget"])
    if ceilings is not None:
        profile.update(ceilings)
        profile["pin"] = {
            **profile["pin"],
            "digest": canonical_budget_profile_digest(
                {k: v for k, v in profile.items() if k != "pin"}
            ),
        }
    manifest["domains"]["budget"] = {
        "component": approved["domains"]["budget"]["component"],
        "mode": "configurable",
        "parameters": {
            "budget_profile": profile["pin"],
            "model_tokens": min(profile["max_model_tokens"], 1000),
            "tool_calls": min(profile["max_tool_calls"], 10),
            "runtime_seconds": min(profile["max_runtime_seconds"], 60),
        },
    }
    lock = {**{json.dumps(p, sort_keys=True): p for p in manifest["lock"]}}
    lock[json.dumps(profile["pin"], sort_keys=True)] = profile["pin"]
    manifest["lock"] = sorted(lock.values(), key=lambda p: (p["kind"], p["id"], p["version"]))
    envelope["bundle_digest"] = json_digest(manifest)
    bundle = parse_runtime_bundle(json.dumps(envelope).encode())
    return bundle, profile, catalog


def test_configurable_budget_within_ceiling_resolves():

    bundle, profile, catalog = _configurable_budget_envelope(settings())
    catalog = dict(catalog, budget=profile)
    from zebra_agent_config.bundle_settings import RuntimeExecutionCatalog

    resolved = RuntimeExecutionCatalog.model_validate(
        dict(
            catalog,
            providers=tuple(catalog["providers"]),
            build_evidence=tuple(catalog["build_evidence"]),
        )
    )
    assembly = resolved.resolve(bundle)
    assert assembly.budget_profile.pin.model_dump(mode="json") == profile["pin"]
    tokens = assembly.bundle.manifest.domains.budget.parameters.model_tokens
    assert tokens <= profile["max_model_tokens"]


def test_configurable_budget_over_ceiling_rejected():
    """同 pin、参数超该 pin 上限——纯超限（批准一致但预算越界）。"""
    import json
    from pathlib import Path

    import pytest
    from agent_core.domain.runtime_assembly import RuntimeAssembly
    from agent_core.domain.runtime_bundle import parse_runtime_bundle
    from agent_core.domain.runtime_bundle_json import json_digest

    assembly, catalog = approved_assembly(settings())
    profile = catalog["budget"]
    envelope = json.loads(
        Path("docs/contracts/runtime-bundle-v1/example-envelope.json").read_bytes()
    )
    manifest = envelope["manifest"]
    approved = assembly.bundle.manifest.model_dump(mode="json")
    manifest.update(baseline_config=approved["baseline_config"], lock=approved["lock"])
    manifest["domains"]["model"]["parameters"] = approved["domains"]["model"]["parameters"]
    manifest["domains"]["instructions"]["parameters"] = approved["domains"]["instructions"][
        "parameters"
    ]
    manifest["domains"]["budget"] = {
        "component": approved["domains"]["budget"]["component"],
        "mode": "configurable",
        "parameters": {
            "budget_profile": profile["pin"],
            "model_tokens": profile["max_model_tokens"] + 1,
            "tool_calls": 0,
            "runtime_seconds": 0,
        },
    }
    lock = {json.dumps(p, sort_keys=True): p for p in manifest["lock"]}
    lock[json.dumps(profile["pin"], sort_keys=True)] = profile["pin"]
    manifest["lock"] = sorted(lock.values(), key=lambda p: (p["kind"], p["id"], p["version"]))
    envelope["bundle_digest"] = json_digest(manifest)
    bundle = parse_runtime_bundle(json.dumps(envelope).encode())
    with pytest.raises(ValueError, match="exceeds exact budget approval"):
        RuntimeAssembly(
            bundle=bundle,
            provider_profile=assembly.provider_profile,
            budget_profile=assembly.budget_profile,
        )


def test_unapproved_budget_pin_rejected_at_resolve():
    from agent_core.domain.runtime_assembly import canonical_budget_profile_digest

    bundle, profile, catalog = _configurable_budget_envelope(settings())
    other = dict(profile, max_tool_calls=profile["max_tool_calls"] + 1)
    other["pin"] = {
        **other["pin"],
        "digest": canonical_budget_profile_digest({k: v for k, v in other.items() if k != "pin"}),
    }
    from zebra_agent_config.bundle_settings import RuntimeExecutionCatalog

    resolved = RuntimeExecutionCatalog.model_validate(
        dict(
            catalog,
            budget=other,
            providers=tuple(catalog["providers"]),
            build_evidence=tuple(catalog["build_evidence"]),
        )
    )
    import pytest

    with pytest.raises(ValueError, match="BUNDLE_BUDGET_NOT_APPROVED"):
        resolved.resolve(bundle)
