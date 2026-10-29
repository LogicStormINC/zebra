# Frozen review: private native helper hostname wiring

Candidate root: `work/private-helper-hostname-fix`. Inherited public commit: `e6f064cf2bc9588d552ac6ede04deaa185f251c5`; the manifest preserves exact inherited file hashes (including approved cumulative private source) and exact candidate hashes. Public source bytes were rechecked against every inherited hash after testing. No public repository/index, Worker/API/schema, QA checker, server, service, container or data was modified. No image rebuild is required.

Exactly three changed paths:

- `cloud-patches/operator/private_workspace_operator.py`
- `cloud-patches/tests/check_private_workspace_hardening.py`
- `cloud-patches/PRIVATE_WORKSPACE_HARDENING_REVIEW.md`

`NativeProof` reads required `helper_hostname` only from the already trusted root configuration. Validation uses existing stdlib `re`: 2+ lowercase ASCII DNS labels, 63 bytes per label and 253 total, no trailing dot or numeric final label, no localhost label. The existing stdlib `socket.getaddrinfo(hostname, None, flags=socket.AI_NUMERICHOST)` parser then rejects successful numeric address parses, including mixed octal/hex abbreviated IPv4. AI_NUMERICHOST prevents DNS lookup; only `socket.gaierror` permits a DNS hostname to proceed. The Docker launch adds exactly one explicit native allowlist env value. Existing fixed network, stdin credentials/nonce, deadline and cleanup logic is unchanged. The native transport's exact env seam was inspected in the captured upstream source; no native transport code was modified.

TDD evidence: expanding the existing offline check first produced `AssertionError` at `assert argv.count('--env') == 1` against inherited operator source. After the minimal implementation, the expanded check passed. Independent SPEC subsequently identified mixed numeric IPv4 spellings accepted by the initial string validation. Adding `127.0x1`, `0x7f.0x1` and `0177.0x1` produced a second expected-fail-closed AssertionError (RED); adding the platform numeric parser then made the same check pass (GREEN). It covers missing/invalid/multiple/malicious values, production and isolated QA hostnames, minimum/maximum hostname lengths, exact single env, arbitrary broad parent env isolation, unchanged packet shape/nonce and mismatch refusal, immutable image/network/user/budget/cleanup gates. The basic check initially encountered a missing isolated source dependency; its two untouched source dependencies were copied with inherited hashes, then both runnable checks passed.

Final runnable checks:

- `python3 work/private-helper-hostname-fix/cloud-patches/tests/check_private_workspace_hardening.py`: PASS (both existing PASS output lines).
- `python3 work/private-helper-hostname-fix/cloud-patches/tests/check_private_workspace.py`: PASS.
- `python3 -m py_compile work/private-helper-hostname-fix/cloud-patches/operator/private_workspace_operator.py work/private-helper-hostname-fix/cloud-patches/tests/check_private_workspace_hardening.py`: PASS syntax only.

This is offline source/check evidence only. The earlier real QA helper positive failure was not HTTP-classified here; the required wiring omission is proven, but it is not established as the only failure. Root must perform independent SPEC then QUALITY review before integration, and separately review exact QA hostname launch configuration before actual native QA. Source review does not authorize activation; no native HTTP success or production acceptance is claimed. No tests bypass native SSRF/TLS/CA/connector validation. Production pause/stop state was not inspected or changed by this slice.

Frozen manifest SHA256: `bb0930a9a16ac5c97b541840cb86117f129f8c965f7a97e4c3bab0687b6ecf90`.
