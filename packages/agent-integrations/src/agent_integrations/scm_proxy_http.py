from __future__ import annotations

import json
import urllib.error
import urllib.request

from agent_integrations.scm_errors import ScmUnavailableError
from agent_integrations.scm_proxy import ScmProxyRequest, ScmProxyResponse


class ScmHttpProxyTransport:
    def __init__(self, *, proxy_endpoint: str) -> None:
        self._proxy_endpoint = proxy_endpoint.strip()
        if not self._proxy_endpoint:
            raise ValueError("proxy_endpoint must not be blank")

    def execute(self, request: ScmProxyRequest) -> ScmProxyResponse:
        proxy_request = urllib.request.Request(
            self._proxy_endpoint,
            data=json.dumps(request.to_transport_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(proxy_request, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
                status_code = response.status
                headers = tuple(response.headers.items())
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            raise ScmUnavailableError(
                f"scm proxy execution failed: {error}",
                metadata={"failure_class": "transport_failure"},
            ) from error
        if not isinstance(body, dict):
            raise ScmUnavailableError(
                "scm proxy execution failed: response body must be a JSON object",
                metadata={"failure_class": "transport_failure"},
            )
        response_body = body.get("body", {})
        if not isinstance(response_body, dict):
            raise ScmUnavailableError(
                "scm proxy execution failed: response body.body must be a JSON object",
                metadata={"failure_class": "transport_failure"},
            )
        response_metadata = body.get("metadata", {})
        if not isinstance(response_metadata, dict):
            raise ScmUnavailableError(
                "scm proxy execution failed: response metadata must be a JSON object",
                metadata={"failure_class": "transport_failure"},
            )
        return ScmProxyResponse(
            status_code=status_code,
            headers=headers,
            body=response_body,
            metadata=response_metadata,
        )
