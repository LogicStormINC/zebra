# CA-OPS-02 verified teardown

Reproduce the guard and owned normal/failure/named-volume live matrix:

```sh
ZEBRA_TEST_DOCKER_CLEANUP_LIVE=1 uv run pytest -q tests/test_disposable_docker_cleanup.py
make test
make check
bash -n tests/conformance/client_v1/run-real-process.sh
```

Run serially on the approved local Docker engine with cached postgres:17-alpine.
The live matrix uses unique IDs, network none, no pull and independent named
sentinels; it never enumerates targets for deletion. Explicit live21 passed;
normal full test gates skip12 live opt-in cases after they were tested separately.

See validation.json for exact results/hashes and retained23 uncertain historical
volumes. Old resources remain intact; no new volumes, containers or networks
remain after this test-only fix. Source-pinned S1 is a separate consumer task.
