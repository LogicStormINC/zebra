"""Import and exercise the real installed SDK without any network/storage writes."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.session import Session
from botocore.stub import Stubber

spec = importlib.util.spec_from_file_location(
    "bootstrap_storage", Path(__file__).with_name("bootstrap_storage.py")
)
assert spec and spec.loader
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


@pytest.mark.parametrize("already_exists", [False, True])
def test_bucket_created_or_reused_then_versioned(monkeypatch, capsys, already_exists):
    values = {
        "ZEBRA_S3_ENDPOINT": "http://minio:9000",
        "ZEBRA_S3_BUCKET": "rabbitmq-product-e2e",
        "ZEBRA_S3_ACCESS_KEY": "sentinel-access",
        "ZEBRA_S3_SECRET_KEY": "sentinel-secret",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    client = Session().create_client(
        "s3",
        endpoint_url="http://minio:9000",
        region_name="us-east-1",
        aws_access_key_id="sentinel-access",
        aws_secret_access_key="sentinel-secret",
    )

    def create_client(service, **kwargs):
        assert service == "s3"
        assert kwargs["endpoint_url"] == "http://minio:9000"
        assert kwargs["config"].s3["addressing_style"] == "path"
        return client

    monkeypatch.setattr(bootstrap, "Session", lambda: SimpleNamespace(create_client=create_client))
    bucket = {"Bucket": "rabbitmq-product-e2e"}
    with Stubber(client) as stub:
        if already_exists:
            stub.add_client_error(
                "create_bucket", "BucketAlreadyOwnedByYou", expected_params=bucket
            )
        else:
            stub.add_response("create_bucket", {}, bucket)
        stub.add_response(
            "put_bucket_versioning", {}, bucket | {"VersioningConfiguration": {"Status": "Enabled"}}
        )
        bootstrap.main()
        stub.assert_no_pending_responses()
    assert "sentinel" not in capsys.readouterr().out


def test_wrong_store_rejected_before_client_creation(monkeypatch):
    monkeypatch.setenv("ZEBRA_S3_ENDPOINT", "http://original:9000")
    monkeypatch.setenv("ZEBRA_S3_BUCKET", "rabbitmq-product-e2e")
    monkeypatch.setattr(bootstrap, "Session", lambda: pytest.fail("created client"))
    with pytest.raises(ValueError, match="non-fixture"):
        bootstrap.main()
