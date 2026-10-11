"""QA bucket setup must verify versioning without touching existing objects."""

from unittest.mock import Mock

import pytest
import scratch_seed
from support import E2EError

SCOPE = "zebra-progress-e2e-qa-123456789abc"


@pytest.fixture
def bucket(monkeypatch):
    environment = {
        "SCRATCH_SCOPE": SCOPE,
        "MINIO_PORT": "32786",
        "MINIO_USER": "qa-user",
        "MINIO_SECRET": "qa-secret",
    }
    row = {
        "NetworkSettings": {"Ports": {"9000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "32786"}]}}
    }
    owned = Mock(return_value=[row])
    monkeypatch.setattr(scratch_seed, "inspect_owned", owned)
    client = Mock()
    client.list_buckets.return_value = {"Buckets": [{"Name": SCOPE}]}
    client.get_bucket_versioning.side_effect = [{}, {"Status": "Enabled"}]
    session = Mock()
    session.create_client.return_value = client
    monkeypatch.setattr("botocore.session.Session", lambda: session)
    return environment, row, owned, client, session


@pytest.mark.parametrize("initial", [{}, {"Status": "Suspended"}])
def test_enables_and_verifies_exact_owned_bucket_without_object_writes(bucket, initial):
    env, _, owned, client, _ = bucket
    client.get_bucket_versioning.side_effect = [initial, {"Status": "Enabled"}]
    scratch_seed.seed_object_bucket(env)
    owned.assert_called_once_with(env, [SCOPE + "-object_store"])
    client.put_bucket_versioning.assert_called_once_with(
        Bucket=SCOPE, VersioningConfiguration={"Status": "Enabled"}
    )
    assert client.get_bucket_versioning.call_count == 2
    assert all(
        call.kwargs == {"Bucket": SCOPE} for call in client.get_bucket_versioning.call_args_list
    )
    assert {call[0] for call in client.mock_calls} == {
        "list_buckets",
        "get_bucket_versioning",
        "put_bucket_versioning",
        "close",
    }


def test_already_enabled_is_read_only(bucket):
    env, _, _, client, _ = bucket
    client.get_bucket_versioning.side_effect = [{"Status": "Enabled"}]
    scratch_seed.seed_object_bucket(env)
    client.put_bucket_versioning.assert_not_called()
    client.close.assert_called_once()


def test_failed_verification_is_not_accepted(bucket):
    env, _, _, client, _ = bucket
    client.get_bucket_versioning.side_effect = [{}, {}]
    with pytest.raises(E2EError, match="scratch_minio_seed_failed"):
        scratch_seed.seed_object_bucket(env)
    client.close.assert_called_once()


@pytest.mark.parametrize("defect", ["scope", "port", "ownership"])
def test_unproved_target_cannot_create_client_or_mutate(bucket, defect):
    env, row, owned, _, session = bucket
    if defect == "scope":
        env["SCRATCH_SCOPE"] = "application"
    elif defect == "port":
        row["NetworkSettings"]["Ports"]["9000/tcp"][0]["HostPort"] = "9000"
    else:
        owned.side_effect = E2EError("scratch_target_not_owned")
    with pytest.raises(E2EError):
        scratch_seed.seed_object_bucket(env)
    session.create_client.assert_not_called()
