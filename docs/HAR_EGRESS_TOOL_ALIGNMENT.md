# Cloud Web Tool Exposure and Egress Alignment

`network_profile` is durable task authority. The Cloud Worker uses its
effective profile to decide which networked Web tools are offered to the
model; filtering tool definitions is a UX optimization, not an authorization
check. Policy still evaluates every proposed call, including a fabricated
tool name or a call restored from a continuation.

- `none`, `setup-only`, `mcp-proxy-only` and `git-proxy-only` do not advertise
  `web.fetch`, `web.search`, `web.crawl` or `web.extract`.
- `domain-allowlist` and `full-trusted-local` may advertise those tools.
  Actual fetch/crawl/extract calls still validate the target URL and exact
  domain match; search checks the configured search endpoint.
- Web Pipeline v2 `web.read` and `web.find` read local cached resources and
  remain available without network egress. They are declared read-only only
  while v2 is enabled.
- V2 `web.search auto_fetch` is rejected outside `full-trusted-local`:
  search-result URLs are not covered by an allowlist on the search endpoint.
- The optional Crawl4AI browser provider is selected only in trusted-local
  mode. Cloud v2 fetch uses the existing no-redirect HTTP provider, retaining
  public-address validation. Do not enable browser fetch in Cloud until its
  complete navigation/subresource egress is governed independently.

Blocked read egress remains recoverable as a failed observation; this does
not turn a blocked route into an authorized request. Tool exposure alone is
never a security boundary.
