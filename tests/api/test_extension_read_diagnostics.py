"""Catalog availability diagnostics must never include exception text or credentials."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from agent_core.ports.extensions import ExtensionStore
from starlette.requests import Request
from zebra_agent_api.extension_reads import extension_read_response

from tests.agent_security.test_extension_authority import _verified


def test_catalog_timeout_logs_only_exception_class(caplog: pytest.LogCaptureFixture) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "headers": [],
            "path": "/v1/extensions/skill-installations",
            "query_string": b"limit=100",
        }
    )
    request.state.verified_host_grant = _verified()
    store = AsyncMock(spec=ExtensionStore)
    store.list_skills.side_effect = TimeoutError("private-dsn password=do-not-log bearer=secret")
    with caplog.at_level(logging.WARNING):
        response = asyncio.run(extension_read_response(request, store=store, deployment="cloud"))
    assert response is not None and response.status_code == 503
    assert "Extension configuration read unavailable: TimeoutError" in caplog.text
    assert "private-dsn" not in caplog.text and "do-not-log" not in caplog.text
    assert "bearer=secret" not in caplog.text


def test_catalog_cancellation_is_not_converted_to_unavailable() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "headers": [],
            "path": "/v1/extensions/skill-installations",
            "query_string": b"",
        }
    )
    request.state.verified_host_grant = _verified()
    store = AsyncMock(spec=ExtensionStore)
    store.list_skills.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(extension_read_response(request, store=store, deployment="cloud"))
