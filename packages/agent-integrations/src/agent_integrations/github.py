from __future__ import annotations

import json
import urllib.error
import urllib.request

from agent_integrations.scm import GitHubPullRequestPayload
from agent_integrations.scm_errors import ScmUnavailableError


class GitHubHttpPullRequestTransport:
    def create_pull_request(
        self,
        payload: GitHubPullRequestPayload,
        *,
        token: str,
    ) -> str:
        request = urllib.request.Request(
            payload.endpoint,
            data=json.dumps(payload.body).encode("utf-8"),
            headers={
                **payload.headers,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            raise ScmUnavailableError(f"github pull request execution failed: {error}") from error
        url = body.get("html_url") if isinstance(body, dict) else None
        if not isinstance(url, str) or not url.strip():
            raise ScmUnavailableError("github pull request response did not include html_url")
        return url
