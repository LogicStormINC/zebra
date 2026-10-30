# CA-P5-06 verification

Run from the Native workspace:

```sh
make test
make check
uv run pytest -q tests/api/test_client_approval_renewal.py \
  tests/api/test_client_approval_operations.py tests/api/test_session_binding_renewal.py \
  tests/api/test_host_binding_renewal_routes.py
# Supply only an isolated nonproduction PostgreSQL DSN:
uv run pytest -q tests/agent_storage/test_client_approval_binding_renewal.py \
  tests/agent_storage/test_client_approval_operations.py
```

The real PG run used a newly created loopback-only disposable PostgreSQL 17
container and isolated fixture schemas, then removed only that owned container.
No existing lab services or business data were changed. Authorization stubbing
in the real PG fixture proves persistence ordering/atomic approval, not signature
verification or current production authority. Separate API and helper tests
cover authorization rejection and frozen renewal ceilings.

Run `make test` and `make check` separately from the unchanged Overdoze workspace.
See validation.json for exact gate results; source-pinned S1 remains separate.
