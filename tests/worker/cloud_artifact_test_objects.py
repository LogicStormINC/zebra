"""Existing MinIO test composition shared outside the Artifact fault matrix."""

import os
from typing import Any

import pytest
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.session import Session  # type: ignore[import-untyped]


def s3_client() -> Any:
    endpoint = os.environ.get("ZEBRA_TEST_S3_ENDPOINT")
    access_key = os.environ.get("ZEBRA_TEST_S3_ACCESS_KEY")
    secret_key = os.environ.get("ZEBRA_TEST_S3_SECRET_KEY")
    if not endpoint or not access_key or not secret_key:
        pytest.skip("set ZEBRA_TEST_S3_* variables to run MinIO tests")
    return Session().create_client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def bucket() -> str:
    return os.environ.get("ZEBRA_TEST_S3_BUCKET", "zebra-artifacts")
