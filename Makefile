PYTHON := uv run

.PHONY: sync check eval test tree api-serve ui-build ui-dev ui-tauri-build ui-tauri-check \
	test-cloud-contracts test-cloud-composition test-cloud-integration \
	test-cloud-faults test-trench-e2e test-gvisor-runtime \
	test-redis-agent-memory release-evidence validate-rollout-candidate \
	validate-rollout-rehearsal

EVIDENCE_ROOT ?= .artifacts/cloud-evidence
CAPABILITIES ?= configs/cloud_release_capabilities.example.json
ROLLOUT_CANDIDATE ?= configs/cloud_rollout_candidate.example.json
RELEASE_MANIFEST ?= $(EVIDENCE_ROOT)/release-manifest.json
ROLLOUT_REHEARSAL ?= $(EVIDENCE_ROOT)/rollout-rehearsal.json

sync:
	uv sync --all-packages --group dev

check:
	uv run python scripts/check_file_sizes.py
	uv run ruff check .
	uv run mypy packages apps
	uv run python scripts/eval_release_check.py

eval:
	uv run python scripts/eval_release_check.py

test:
	uv run pytest

test-cloud-contracts:
	uv run python scripts/run_cloud_gate.py --gate cloud-contracts \
		--evidence-dir "$(EVIDENCE_ROOT)/cloud-contracts" -- \
		uv run pytest -q --junitxml="$(EVIDENCE_ROOT)/cloud-contracts/junit.xml" \
		tests/agent_core/test_client_effect_contracts.py \
		tests/agent_core/test_agent_memory_gateway_contract.py \
		tests/agent_integrations/test_host_tools.py \
		tests/agent_integrations/test_client_effect_projection.py \
		tests/agent_integrations/test_client_state_projection.py \
		tests/agent_integrations/redis_agent_memory/test_redis_agent_memory_gateway.py \
		tests/agent_runtime/test_process_execution.py \
		tests/agent_observability/test_execution_metrics.py

test-cloud-composition:
	uv run python scripts/run_cloud_gate.py --gate cloud-composition \
		--evidence-dir "$(EVIDENCE_ROOT)/cloud-composition" -- \
		uv run pytest -q --junitxml="$(EVIDENCE_ROOT)/cloud-composition/junit.xml" \
		tests/api/test_agui_client_admission.py \
		tests/api/test_client_effect_agui_stream.py \
		tests/worker/test_runtime_factory.py \
		tests/worker/test_client_state_recovery.py \
		tests/worker/test_cloud_composition.py \
		tests/worker/test_client_tool_gateway.py \
		tests/worker/test_host_egress.py \
		tests/scheduler

test-cloud-integration:
	uv run python scripts/run_cloud_gate.py --gate cloud-integration \
		--timeout-seconds 3600 --evidence-dir "$(EVIDENCE_ROOT)/cloud-integration" -- \
		uv run python tests/compose/cloudline/run_real_service.py --all \
		--evidence-dir "$(EVIDENCE_ROOT)/cloud-integration/services"

test-cloud-faults:
	ZEBRA_CLOUD_FAULTS_EVIDENCE_DIR="$(abspath $(EVIDENCE_ROOT))/cloud-faults" \
	uv run python scripts/run_cloud_gate.py --gate cloud-faults \
		--evidence-dir "$(EVIDENCE_ROOT)/cloud-faults" -- \
		bash tests/compose/cloud_faults/run-postgres-tests.sh

test-trench-e2e:
	ZEBRA_TRENCH_READ_E2E_EVIDENCE_DIR="$(abspath $(EVIDENCE_ROOT))/trench-e2e" \
	uv run python scripts/run_cloud_gate.py --gate trench-e2e \
		--timeout-seconds 2400 --evidence-dir "$(EVIDENCE_ROOT)/trench-e2e" -- \
		uv run python tests/compose/trench_read_e2e/run_acceptance.py

test-gvisor-runtime:
	test "$${ZEBRA_GVISOR_SMOKE:-}" = "1"
	test -n "$${ZEBRA_GVISOR_IMAGE:-}"
	uv run python scripts/run_cloud_gate.py --gate gvisor-runtime \
		--evidence-dir "$(EVIDENCE_ROOT)/gvisor-runtime" -- \
		uv run pytest -q --junitxml="$(EVIDENCE_ROOT)/gvisor-runtime/junit.xml" \
		tests/agent_runtime/test_gvisor_smoke.py

test-redis-agent-memory:
	test "$${ZEBRA_TEST_REDIS_AGENT_MEMORY_ALLOW_DATA:-}" = "true"
	test -n "$${ZEBRA_TEST_REDIS_AGENT_MEMORY_ENDPOINT:-}"
	test -n "$${ZEBRA_TEST_REDIS_AGENT_MEMORY_STORE_ID:-}"
	test -n "$${ZEBRA_TEST_REDIS_AGENT_MEMORY_API_KEY:-}"
	uv run python scripts/run_cloud_gate.py --gate redis-agent-memory \
		--evidence-dir "$(EVIDENCE_ROOT)/redis-agent-memory" -- \
		uv run pytest -q --junitxml="$(EVIDENCE_ROOT)/redis-agent-memory/junit.xml" \
		tests/agent_integrations/redis_agent_memory/test_live_contract.py

release-evidence:
	uv run python scripts/build_release_evidence.py \
		--capabilities "$(CAPABILITIES)" \
		--evidence-root "$(EVIDENCE_ROOT)" \
		--output "$(EVIDENCE_ROOT)/release-manifest.json"

validate-rollout-candidate:
	uv run python scripts/validate_rollout_candidate.py \
		--candidate "$(ROLLOUT_CANDIDATE)" \
		--release-manifest "$(RELEASE_MANIFEST)" \
		--output "$(EVIDENCE_ROOT)/rollout-attestation.json"

validate-rollout-rehearsal:
	uv run python scripts/validate_rollout_rehearsal.py \
		--candidate "$(ROLLOUT_CANDIDATE)" \
		--attestation "$(EVIDENCE_ROOT)/rollout-attestation.json" \
		--rehearsal "$(ROLLOUT_REHEARSAL)" \
		--output "$(EVIDENCE_ROOT)/rollout-rehearsal-verdict.json"

tree:
	find apps packages tests -maxdepth 3 | sort

api-serve:
	uv run uvicorn zebra_agent_api.http:create_http_app --factory --host 127.0.0.1 --port 8000

ui-build:
	cd UI/desktop && CI=true pnpm install --ignore-scripts && pnpm build

ui-dev:
	cd UI/desktop && CI=true pnpm install --ignore-scripts && pnpm dev

ui-tauri-build:
	cd UI/desktop && CI=true pnpm install --ignore-scripts && pnpm tauri:build

ui-tauri-check:
	cd UI/desktop && CI=true pnpm install --ignore-scripts && pnpm tauri:check
