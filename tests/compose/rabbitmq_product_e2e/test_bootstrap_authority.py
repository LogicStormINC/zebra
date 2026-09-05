"""Bootstrap target guards using fake identities and a no-I/O registry recorder."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "bootstrap_authority", Path(__file__).with_name("bootstrap_authority.py")
)
assert spec and spec.loader
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


@pytest.mark.parametrize("database", ["zebra_e2e", "zebra_stage3_e2e"])
def test_exact_databases_keep_original_authority(monkeypatch, database):
    monkeypatch.setenv("ZEBRA_DEPLOYMENT_NAMESPACE", "rabbitmq-product-e2e")
    monkeypatch.setenv("ZEBRA_DATABASE_URL", f"postgresql://e2e:fake@postgres:5432/{database}")
    monkeypatch.setattr(
        bootstrap.importlib,
        "import_module",
        lambda _name: SimpleNamespace(__file__="/app/packages/fake/__init__.py"),
    )
    records = []
    monkeypatch.setattr(
        bootstrap,
        "PostgresHostAuthorityStore",
        lambda *_args, **_kwargs: SimpleNamespace(upsert_registry=records.append),
    )
    bootstrap.main()
    assert records[0].namespace_id == "trench-rabbitmq-e2e"
    assert records[0].issuer == "https://broker.zebra.local:28443"
    assert records[0].allowed_origins == ("https://127.0.0.1:28443",)


@pytest.mark.parametrize(
    "target",
    [
        "postgresql://e2e:fake@postgres:5432/other",
        "postgresql://e2e:fake@foreign:5432/zebra_stage3_e2e",
        "postgresql://e2e:fake@postgres:5433/zebra_stage3_e2e",
        "postgresql://other:fake@postgres:5432/zebra_stage3_e2e",
        "postgresql://e2e:fake@postgres:5432/zebra_stage3_e2e?hostaddr=203.0.113.1",
    ],
)
def test_other_database_targets_rejected_before_store(monkeypatch, target):
    monkeypatch.setenv("ZEBRA_DEPLOYMENT_NAMESPACE", "rabbitmq-product-e2e")
    monkeypatch.setenv("ZEBRA_DATABASE_URL", target)
    monkeypatch.setattr(
        bootstrap, "PostgresHostAuthorityStore", lambda *_a, **_kw: pytest.fail("store opened")
    )
    with pytest.raises(ValueError, match="non-fixture database"):
        bootstrap.main()
