#!/usr/bin/env python3
"""Validate or publish one immutable Client frontend profile release."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from agent_core.domain.client_capabilities import FrontendCapabilityProfileVersion


def main() -> int:
    args = _arguments()
    manifest = json.loads(args.profile.read_text())
    profile = FrontendCapabilityProfileVersion.model_validate(manifest.get("profile", manifest))
    if manifest.get("profile_digest", profile.profile_digest) != profile.profile_digest:
        raise SystemExit("release manifest digest differs from profile contents")
    print(json.dumps({"profile_digest": profile.profile_digest, "revision": profile.revision}))
    if args.check_only:
        return 0
    token = args.token or os.environ.get("ZEBRA_PLATFORM_OPERATOR_TOKEN", "")
    if not token:
        raise SystemExit("ZEBRA_PLATFORM_OPERATOR_TOKEN is required")
    base = args.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    current = _request(
        "GET",
        f"{base}/platform/v1/frontend-profiles/{profile.frontend_app_id}/revisions/{profile.revision}",
        headers,
        allow_not_found=True,
    )
    if current is None:
        latest = _request(
            "GET",
            f"{base}/platform/v1/frontend-profiles/{profile.frontend_app_id}",
            headers,
            allow_not_found=True,
        )
        if latest is not None and profile.revision <= int(latest["revision"]):
            raise SystemExit("changed profiles must increase the published revision")
        if args.verify_only:
            raise SystemExit("profile revision is not published")
        _request(
            "POST",
            f"{base}/platform/v1/frontend-profiles"
            + (f"/{profile.frontend_app_id}/versions" if latest else ""),
            headers,
            profile.model_dump(mode="json"),
        )
    elif current.get("profile_digest") != profile.profile_digest:
        raise SystemExit("published profile revision has a different digest")
    elif current.get("lifecycle", "published") != "published":
        raise SystemExit("profile revision is not active")
    binding_url = (
        f"{base}/platform/v1/frontend-profile-bindings/"
        f"{args.host_app_id}/{args.namespace_id}/{profile.frontend_app_id}"
    )
    current_binding = _request(
        "GET",
        binding_url,
        headers,
        allow_not_found=True,
    )
    if current_binding is not None and (
        current_binding.get("profile_digest") == profile.profile_digest
        and current_binding.get("revision") == profile.revision
    ):
        print(
            json.dumps(
                {"binding": current_binding, "status": "already_published"},
                sort_keys=True,
            )
        )
        return 0
    if args.verify_only:
        raise SystemExit("frontend profile binding does not match this release")
    expected_binding_revision = (
        args.expected_binding_revision
        if args.expected_binding_revision is not None
        else int(current_binding.get("binding_revision", 0) if current_binding else 0)
    )
    binding = _request(
        "POST",
        f"{base}/platform/v1/frontend-profile-bindings",
        headers,
        {
            "expected_binding_revision": expected_binding_revision,
            "frontend_app_id": profile.frontend_app_id,
            "host_app_id": args.host_app_id,
            "namespace_id": args.namespace_id,
            "profile_digest": profile.profile_digest,
            "revision": profile.revision,
        },
    )
    verified = _request("GET", binding_url, headers)
    if (
        verified is None
        or verified.get("profile_digest") != profile.profile_digest
        or verified.get("revision") != profile.revision
    ):
        raise SystemExit("published binding verification failed")
    print(json.dumps({"binding": binding, "status": "published"}, sort_keys=True))
    return 0


def _request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, object] | None = None,
    *,
    allow_not_found: bool = False,
) -> dict[str, object] | None:
    request = urllib.request.Request(
        url,
        data=(json.dumps(body).encode() if body is not None else None),
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if allow_not_found and exc.code == 404:
            return None
        detail = exc.read().decode(errors="replace")[:1000]
        raise SystemExit(f"profile release failed: HTTP {exc.code}: {detail}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("profile release returned a non-object response")
    return payload


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--token", default="")
    parser.add_argument(
        "--profile",
        type=Path,
        required=True,
    )
    parser.add_argument("--host-app-id")
    parser.add_argument("--namespace-id")
    parser.add_argument("--expected-binding-revision", type=int)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Read-only deployment gate: require matching active profile and binding",
    )
    args = parser.parse_args()
    if not args.check_only and (not args.host_app_id or not args.namespace_id):
        parser.error("publishing requires explicit --host-app-id and --namespace-id")
    return args


if __name__ == "__main__":
    sys.exit(main())
