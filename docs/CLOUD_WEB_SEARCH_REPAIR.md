# Cloud search and exact-link delivery repair

## Verified incident

Trench conversation `conv_1791784350642_9757c5` maps to Task/session
`6721d0b0-f777-4f91-9746-38b7abf25874`; latest recovery execution is session
`301ee0ef-a462-48ba-9134-cf456ef2dea4`. Its goal asks whether network search
is available. It already has `general` tools and `full-gateway` network authority.

The restarted Worker remains running with restart count zero. This failure is
not the preceding pool/startup incident. At sequence125, delivery assessment
has exactly one unmet requirement: `citation_uses_exact_collected_url`.
The source `https://www.itjuzi.com/api/telegraph.xml` was collected, but the URL
scanner consumed its closing Markdown backtick and adjacent Chinese prose.
The resulting artificial URL caused the answer to be suspended.

Two independent capability defects were verified:

- No search endpoint was configured, so `web.search` was absent. Base application
  Compose also failed to forward this setting to containers.
- Public domains inside the Worker resolved to Clash Fake-IP `198.18.0.0/15`.
  Correct private-address protection therefore rejected otherwise public fetches.
  A bounded TLS-verified Cloudflare DoH request from the same Worker succeeded.

## Repair and boundaries

- Backticks delimit URL candidates; exact-reference checks remain mandatory.
  Invented and annotation-extended URLs still fail.
- Legacy `web.search` now emits its bounded normalized result URLs as explicit
  evidence refs. Before repair, its plain-text output could be visible to the
  model while absent from the durable evidence ledger. Both live settlement and
  event replay are checked. Fetch metadata now preserves the canonical requested
  URL, count and untrusted flag instead of accepting transport overrides.
- Public direct HTTPS now uses the existing MCP pinned socket implementation.
  It keeps certificate verification and hostname SNI, disables redirects/proxies
  in cloud mode and validates the actual socket address against rebinding.
- Only exclusively Fake-IP DNS answers trigger public DoH recovery. The resolver
  is fixed at `https://1.1.1.1/dns-query`, uses three-second reads and a64KiB
  response cap, checks the requested question and accepts only public A answers.
  Mixed DNS, private, loopback, metadata, multicast and reserved addresses fail.
  Fake-IP fallback sends the requested public hostname to Cloudflare; it does
  not modify system DNS, trust Fake-IP sockets or install a global DNS cache.
- Legacy and native-v2 search share fixed operator backend admission. The
  `ZEBRA_WEB_SEARCH_PRIVATE_BACKEND` option defaults false. When explicitly
  enabled, only the configured HTTPS origin/path/fixed query can use RFC1918/ULA
  backend addresses. TLS stays verified. Metadata/loopback/Fake-IP are excluded.
  Tool arguments cannot change this endpoint. Search result fetches do not inherit
  the exception, and MCP/public fetch keep their ordinary public-only boundary.
- DNS outages return typed unavailable errors, not false private-policy denials;
  native resolution preserves typed errors instead of crashing its child process.
- Native subprocess protocol carries backend authority across process boundaries;
  existing kill/reap, cancellation, output bounds and ownership checks remain.
- Independent SearXNG serves JSON behind a separate TLS proxy. Raw backend has no
  host port or shared dependency-network exposure. Only `/search` and `/healthz`
  are proxied. Search access logs are discarded. Images are digest-pinned for
  arm64/amd64; backend CPU/memory/process/connections are bounded.

This is a local private operator composition, not a qualified public search
cluster. It has no tenant query logging, production autoscaling, distributed
rate-limiter or SLA. A high-load deployment needs operator admission, per-tenant
quotas, observability and independently qualified upstream engines. This repair
does not change strict data-coverage certification or qualify the failed SQL gate.

## Operator-only startup

Run from the primary checkout, after integrating this source branch. No command
below performs business-data cleanup or resubmits the failed task.

```sh
cd /Users/lukeding/Desktop/playground/2026/product/zebra-agent

# Generate search leaf certificate/service secret using the existing local CA.
# Does not replace the CA, modify acceptance.env or start services.
bash docker/web-search/bootstrap.sh

# Start only the independent search stack.
docker compose --env-file docker/trench-acceptance.env \
  -f docker/web-search/compose.yml up -d --wait

# Optional: images were prepared by this repair. Rebuild only after source changes
# or when the image IDs do not match the validation record below.
docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml \
  -f docker/compose.local-gvisor.yml \
  -f docker/compose.coverage-pro-test.yml \
  -f docker/compose.web-search.yml build zebra-api zebra-worker

docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml \
  -f docker/compose.local-gvisor.yml \
  -f docker/compose.coverage-pro-test.yml \
  -f docker/compose.web-search.yml \
  up -d --no-build --no-deps --force-recreate --wait zebra-api zebra-worker
```

An expired acceptance CA is a separate operator certificate-renewal task: this
bootstrap deliberately fails instead of silently replacing the shared trust root.
Rerun search bootstrap after a CA renewal; it checks leaf signature as well as
expiry. New leaf lifetime is14days; renewal must be followed by search TLS reload.
The Worker must retain its existing `SSL_CERT_FILE` acceptance/public CA bundle.
The overlay does not change frozen Task authority; new Tasks still need a signed
`full-gateway` profile. It does not turn `none` Tasks into network-enabled Tasks.

## Manual acceptance

```sh
# TLS + JSON + upstream-engine check, without submitting a model task.
curl --fail --silent --show-error \
  --cacert docker/trench-acceptance/secrets/ca.crt \
  --resolve search.zebra.test:18445:127.0.0.1 \
  'https://search.zebra.test:18445/search?q=OpenAI&format=json' \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); assert isinstance(p.get("results"),list); assert not p.get("unresponsive_engines") and not p.get("error"), "search engines incomplete"; assert p["results"], "no candidates"; print("search candidates:", len(p["results"]))'
```

Then use a new test conversation requesting public search with source links.
Verify `web.search` is actually called, source URLs are collected, the answer
finishes and no `delivery_requirements_unmet`/Worker restart appears. The old
suspended attempt is not automatically resumed or rewritten by this repair.

HTTP200/health alone is not search or conversation acceptance. Upstream CAPTCHA,
rate limits and engine outages remain failures, not successful empty results;
adjust qualified engines in `docker/web-search/settings.yml` if necessary.

Primary documentation: [SearXNG installation](https://docs.searxng.org/admin/installation-docker.html)
and [JSON search API](https://docs.searxng.org/dev/search_api.html).

## Source/image validation record - 2026-10-12

- Source96a817bc fast-forwarded locally into `cloud-agent-trench`. Primary
  postmerge critical46passed0skipped2.20s; both Compose definitions validate.
  Original dirty SDK files and all stash refs have unchanged SHA256 digests.
  No GitHub push or service restart was performed.

- Final affected cross-package gate:1602passed12environment-skipped,92.09s;
  runtime/tools/config/security/Worker authority plus exact citation regressions.
  This is not the full repository suite or strict SQL/semantic coverage gate.
- `make check`: file size/Ruff/mypy1245/eval30 GO.
- Independent search and combined application Compose configurations validate;
  scratch bootstrap proves CA preservation, secret reuse, permissions and SAN.
  Pinned SearXNG image loaded both configured engines and JSON format with secret
  override, offline. Pinned Caddy adapted the supplied config, offline.
- Disposable new-image probe on `zebra-dependencies` obtained public HTTPS200,
  577-byte response and nonempty projected source text in3.181s. System DNS still
  returned198.18.0.161. No model call, original Task mutation or service restart.
- Six modified runtime/core/tool module SHA256 values match image contents.
- Prepared application image IDs (all arm64):
  - API:`25b8306057d8fb822572e93ab3f35cebd1b6aa4fee9cfcf6fe05d564763ed837`
  - Worker:`aec421e851e9165394d5f16174f4c125f493cbc4fdc7ab7a24f1e2471ea16028`
  - Migrate:`1e46019b55e4b04d10a51e2a072fa5a38cb78cce60ce50f07692e664d1c9ac40`
- Existing Worker intentionally still uses398be364 with restart count0. Image
  build does not replace a running container. SearXNG and a new test conversation
  must still be started/accepted by the operator before declaring live closure.
