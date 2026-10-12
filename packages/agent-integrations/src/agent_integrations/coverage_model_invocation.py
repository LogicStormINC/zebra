"""Opt-in MODEL composition; fresh authority callbacks own Event/STOP/Host proof.

The Artifact store must expose only FINALIZED immutable private evidence through
the existing Ports (the future CloudCoverageArtifacts facade). Gateway factories
must supply fresh gateways/clients: used real HTTP pools remain unsupported.
This component neither activates a Worker nor proves live transport origin.
Delegate checks validate trusted composition, not arbitrary Python/process patches.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import httpx
from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError, coverage_digest
from agent_core.domain.coverage_model_budget import (
    CoverageModelBudgetState,
    CoverageModelPolicy,
    CoverageModelReservation,
    CoverageModelReservationResult,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_model_checkpoint import (
    MAX_MODEL_CHECKPOINT_BYTES,
    MODEL_CHECKPOINT_KIND,
    CoverageModelCheckpoint,
    completion_usage,
    decode_model_checkpoint,
    model_checkpoint_id,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding, canonical_coverage_bytes
from agent_core.domain.coverage_snapshot import CoverageRecord
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.coverage_validation import CoverageUnitKey
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelInvocationPolicy
from agent_core.ports.coverage_model_budget import CoverageModelBudgetStorePort

from agent_integrations.coverage_model_completion import (
    decode_model_completion,
    encode_model_completion,
)
from agent_integrations.coverage_model_delegates import _validate_gateway_delegates
from agent_integrations.coverage_model_derivation import (
    derive_semantic_observation,
    validate_semantic_request,
    validate_semantic_response_identity,
)
from agent_integrations.coverage_model_policy import (
    POLICY_KIND,
    REVIEWER_PROFILE,
    OfficialDeepSeekPolicy,
)
from agent_integrations.coverage_model_settlement import settle_checkpoint
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts, artifact_id
from agent_integrations.coverage_snapshot_invocation import unique_object
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CoverageModelInvocation:
    def __init__(
        self,
        *,
        binding: CoverageRunBinding,
        artifacts: CoverageArtifacts,
        budget_store: CoverageModelBudgetStorePort,
        original_policy: CoverageModelPolicy,
        fresh_fence: Callable[[], LeaseFence],
        check_authority: Callable[[], None],
        gateway_factory: Callable[[], OpenAICompatibleModelGateway],
        trusted_proof: OfficialDeepSeekPolicy,
        allow_mock_transport: bool = False,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """check_authority must sync Events and verify current Task/Host/STOP authority.

        Original admission/binding/profile/deadline are independently checked by
        initialize_model_budget; caller-provided policy alone grants nothing.
        Membership is verified once; eager boundaries re-read its lifecycle.
        Admitted incremental execution defers historical reads to certification.
        Production uses the native owned TLS-verifying fresh client only. Explicit
        allow_mock_transport is a trusted test seam, never an origin/capacity proof.
        """
        try:
            self.binding = CoverageRunBinding.model_validate(
                coverage_admission_input(binding), strict=True
            )
            self.policy = CoverageModelPolicy.model_validate(
                coverage_admission_input(original_policy), strict=True
            )
            if type(trusted_proof) is not OfficialDeepSeekPolicy:
                raise ValueError("explicit configured official proof required")
            self.proof = OfficialDeepSeekPolicy(
                trusted_proof.original_metadata,
                trusted_proof.metadata_url,
                trusted_proof.chat_url,
                trusted_proof.version,
            )
            self.definition = semantic_check(REVIEWER_PROFILE)
            if (
                type(allow_mock_transport) is not bool
                or self.policy.model_profile != REVIEWER_PROFILE
                or self.definition.contract_check not in self.binding.contract.checks
                or self.binding.snapshot.source_resource_ref is None
                or artifacts.session != self.binding.session_id
                or not all(
                    callable(value)
                    for value in (
                        fresh_fence,
                        check_authority,
                        gateway_factory,
                        now,
                    )
                )
            ):
                raise ValueError("unsupported original MODEL composition")
            self.artifacts, self.store = artifacts, budget_store
            self.fresh_fence, self.check_authority = fresh_fence, check_authority
            self.gateway_factory, self.now = gateway_factory, now
            self.allow_mock_transport = allow_mock_transport
            self._retained_until: datetime | None = None
            self._manifest: bytes | None = None
            self._policy_bytes: bytes | None = None
            self._checkpoint: tuple[ArtifactId, bytes] | None = None
            self._defer_boundary_proof = False
            manifest_ref = self.binding.snapshot.manifest_artifact_ref
            self.manifest_id = ArtifactId(UUID(manifest_ref.removeprefix("artifact://")))
            if manifest_ref != f"artifact://{self.manifest_id}":
                raise ValueError("original manifest requires canonical Artifact identity")
            self.policy_id = artifact_id(
                self.binding.session_id,
                {
                    "kind": POLICY_KIND,
                    "binding": self.binding.model_dump(mode="json"),
                },
            )
            self._boundary()
            self._manifest = self._required(self.manifest_id, "coverage_manifest")
            rows = self.binding.verify_manifest(self._manifest)
            self.records: dict[tuple[str, str], CoverageRecord] = {
                row.identity: row for row in rows
            }
            actual = self.store.initialize_model_budget(self.binding, fence=self._fence())
            if CoverageModelPolicy.model_validate(coverage_admission_input(actual)) != self.policy:
                raise ValueError("caller policy differs from original admitted MODEL policy")
            self._freeze_policy()
            self._defer_boundary_proof = self.policy.validation_mode == "final_certification"
            self._boundary()
        except CoverageRefusedError:
            raise
        except (ValueError, TypeError, RecursionError, OverflowError) as error:
            raise CoverageRefusedError(Reason.UNSUPPORTED) from error

    def _time(self) -> datetime:
        current = self.now()
        if type(current) is not datetime or current.utcoffset() is None:
            raise CoverageRefusedError(Reason.UNSUPPORTED)
        if not self.binding.snapshot.as_of <= current < self.binding.snapshot.expires_at:
            raise CoverageRefusedError(Reason.SNAPSHOT_EXPIRED)
        if not self.policy.started_at <= current < self.policy.deadline:
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
        if self._retained_until is not None and self._retained_until <= current:
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
        return current

    def _load(
        self, identifier: ArtifactId, kind: str, *, expected: bytes | None = None,
    ) -> bytes | None:
        loaded = self.artifacts.load_payload(
            identifier,
            kind,
            MAX_MODEL_CHECKPOINT_BYTES,
            self._time(),
            mime_type="application/octet-stream"
            if kind == "coverage_manifest"
            else "application/json",
            expected_digest=None if expected is None else sha256(expected).hexdigest(),
        )
        if loaded is not None:
            metadata = loaded[0]
            if metadata.retained_until is not None:
                self._retained_until = min(
                    self._retained_until or metadata.retained_until, metadata.retained_until
                )
            self._time()  # A long object read cannot renew retention or original deadlines.
            return loaded[1]
        return None

    def _required(
        self, identifier: ArtifactId, kind: str, *, expected: bytes | None = None,
    ) -> bytes:
        body = self._load(identifier, kind, expected=expected)
        if body is None:
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
        return body

    def _boundary(self) -> datetime:
        try:
            self.check_authority()
            if self._defer_boundary_proof:
                # Only after native admission and initial frozen proof verification.
                # Current loads/settlement/acceptance and independent full final
                # proof remain required; this is not a permission or budget cache.
                current = self._time()
                # Only the native clock is pure; injected clocks can revoke
                # authority during their callback. Real reads guard both ends.
                if self.now is not _utc_now:
                    self.check_authority()
                return current
            # ponytail: O(n) manifest I/O per boundary, membership parses once.
            # Upgrade via the existing governed lifecycle facade for large runs.
            for identifier, kind, expected in (
                (self.manifest_id, "coverage_manifest", self._manifest),
                (self.policy_id, POLICY_KIND, self._policy_bytes),
            ):
                if expected is not None and self._required(
                    identifier, kind, expected=expected,
                ) != expected:
                    raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
            if self._checkpoint is not None:
                identifier, expected = self._checkpoint
                if self._required(identifier, MODEL_CHECKPOINT_KIND, expected=expected) != expected:
                    raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
            self.check_authority()
            return self._time()
        except CoverageRefusedError:
            raise
        except Exception as error:
            raise CoverageRefusedError(Reason.AUTHORITY_INVALID) from error

    def _fence(self) -> LeaseFence:
        self._boundary()
        fence = LeaseFence.model_validate(coverage_admission_input(self.fresh_fence()), strict=True)
        self.check_authority()
        self._time()
        return fence

    def _preparation_boundary(self) -> datetime:
        """Legacy callers guard every helper; native owners may qualify pure preparation."""
        return self._boundary()

    def _mutation_fence(self) -> LeaseFence:
        """Copying a fence grants no right: the mutation owns its fresh post-lock check."""
        return self._fence()

    def _publish_checkpoint(self, identifier: ArtifactId, body: bytes) -> bool:
        """Legacy publication leaves usage to its separate verified settlement."""
        self.artifacts.publish(
            identifier, MODEL_CHECKPOINT_KIND, body, MAX_MODEL_CHECKPOINT_BYTES,
            self._preparation_boundary, self.binding.snapshot.expires_at,
            mime_type="application/json",
        )
        if self._required(identifier, MODEL_CHECKPOINT_KIND) != body:
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
        return False

    def _recover_checkpoint(
        self, identifier: ArtifactId, reservation: CoverageModelReservation,
    ) -> bytes | None:
        """Only an exact native owner may recover private staged evidence."""
        return None

    def _freeze_policy(self) -> None:
        existing = self._load(self.policy_id, POLICY_KIND)
        state = CoverageModelBudgetState.model_validate(
            coverage_admission_input(self.store.model_budget_state(self.binding)), strict=True
        )
        if state.policy != self.policy:
            raise ValueError("original budget policy changed")
        if existing is None:
            if state.calls:
                raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
            existing = canonical_coverage_bytes(
                {
                    "schema": "coverage-model-policy/1",
                    "scope": "internal",
                    "binding": self.binding.model_dump(mode="json"),
                    "original_policy": self.policy.model_dump(mode="json"),
                    "metadata": self.proof.original_metadata.decode("utf-8"),
                    "effective": self.proof.effective,
                    "capacity_hash": self.proof.capacity_hash,
                }
            )
            self.artifacts.publish(
                self.policy_id,
                POLICY_KIND,
                existing,
                MAX_MODEL_CHECKPOINT_BYTES,
                self._boundary,
                self.binding.snapshot.expires_at,
                mime_type="application/json",
            )
        data = json.loads(existing, object_pairs_hook=unique_object)
        if (
            type(data) is not dict
            or set(data)
            != {
                "schema",
                "scope",
                "binding",
                "original_policy",
                "metadata",
                "effective",
                "capacity_hash",
            }
            or type(data["metadata"]) is not str
        ):
            raise ValueError("invalid original policy Artifact")
        saved = OfficialDeepSeekPolicy(data["metadata"].encode("utf-8"))
        if (
            canonical_coverage_bytes(data) != existing
            or data["schema"] != "coverage-model-policy/1"
            or data["scope"] != "internal"
            or canonical_coverage_bytes(data["binding"])
            != canonical_coverage_bytes(self.binding.model_dump(mode="json"))
            or canonical_coverage_bytes(data["original_policy"])
            != canonical_coverage_bytes(self.policy.model_dump(mode="json"))
            or canonical_coverage_bytes(data["effective"])
            != canonical_coverage_bytes(saved.effective)
            or saved.effective != self.proof.effective
            or data["capacity_hash"] != saved.capacity_hash
        ):
            raise ValueError("original effective MODEL policy changed")
        self._policy_bytes = existing
        if self._required(self.policy_id, POLICY_KIND) != existing:
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)

    def __call__(
        self, messages: list[SessionMessage], invocation_policy: ModelInvocationPolicy
    ) -> ModelCompletion:
        owned_registry_data: dict[object, object] | None = None
        try:
            self._preparation_boundary()
            self._checkpoint = None
            gateway = self.gateway_factory()
            _validate_gateway_delegates(gateway)
            owned_registry_data = vars(gateway._prepared_requests._issued)["data"]
            if gateway._client is not None and not (
                self.allow_mock_transport
                and type(gateway._client) is httpx.Client
                and type(gateway._client._transport) is httpx.MockTransport
                and gateway._client.trust_env is False
                and gateway._client.follow_redirects is False
            ):
                raise ValueError(
                    "official MODEL requires native owned TLS or explicit trusted mock"
                )
            prepared = gateway.prepare_text_request(messages, invocation_policy=invocation_policy)
            if (
                prepared.endpoint != self.proof.chat_url
                or prepared.provider != "deepseek"
                or prepared.default_model != self.proof.effective["model"]
                or prepared.resolved.profile.profile_id != REVIEWER_PROFILE
            ):
                raise ValueError("strict MODEL requires pinned official gateway/model/profile")
            request = json.loads(prepared.body)
            payload = json.loads(request["messages"][1]["content"], object_pairs_hook=unique_object)
            key = CoverageUnitKey.model_validate(payload["key"])
            record = self.records.get((key.record_id, key.content_digest))
            if record is None:
                raise ValueError("semantic source is outside the verified manifest")
            validate_semantic_request(self.binding, prepared.body, self.definition, key, record)
            if self.policy.max_tokens < self.proof.context_window:
                raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
            reservation = CoverageModelReservation(
                reservation_key="model-"
                + coverage_digest(
                    {
                        "binding": self.binding.model_dump(mode="json"),
                        "unit": key.model_dump(mode="json"),
                    }
                ),
                admission_digest=self.policy.admission_digest,
                key=key,
                request_digest=prepared.request_digest,
                model_profile=REVIEWER_PROFILE,
                token_bound=self.proof.context_window,
            )
            # Factories/preparation are extensible. Observe any revocation they
            # caused before reserving a charge, even for a qualified native owner.
            self._boundary()
            result = CoverageModelReservationResult.model_validate(
                coverage_admission_input(
                    self.store.reserve_model_call(
                        self.binding, reservation, fence=self._mutation_fence(),
                    )
                ),
                strict=True,
            )
            if result.reservation != reservation or (result.invoke and result.receipt is not None):
                raise ValueError("reservation result conflicts with exact prepared request")
            self._preparation_boundary()
            _validate_gateway_delegates(gateway, prepared)
            identifier = model_checkpoint_id(self.binding, reservation)
            body = self._load(identifier, MODEL_CHECKPOINT_KIND)
            usage_settled = False
            recovered = False
            if body is None and not result.invoke:
                body = self._recover_checkpoint(identifier, reservation)
                recovered = body is not None
            if body is None:
                if not result.invoke:
                    raise CoverageRefusedError(Reason.UNRESOLVED_FAILURE)
                self._boundary()
                _validate_gateway_delegates(gateway, prepared)
                response = gateway.complete_prepared(prepared)  # Exactly one attempt; never retry.
                self._boundary()  # Transport callbacks cannot grant the next publication.
                completion = encode_model_completion(response)
                validate_semantic_response_identity(self.definition, response)
                checkpoint = CoverageModelCheckpoint(
                    self.binding, reservation, completion, prepared.body
                )
                body = checkpoint.canonical_bytes
                usage_settled = self._publish_checkpoint(identifier, body)
                if type(usage_settled) is not bool:
                    raise ValueError("checkpoint owner must return an explicit usage outcome")
            checkpoint = decode_model_checkpoint(body)
            if (
                checkpoint.binding != self.binding
                or checkpoint.reservation != reservation
                or checkpoint.request != prepared.body
            ):
                raise ValueError("original checkpoint conflicts with prepared request")
            if recovered:
                usage_settled = self._publish_checkpoint(identifier, body)
                if type(usage_settled) is not bool:
                    raise ValueError("checkpoint owner must return an explicit usage outcome")
            response = decode_model_completion(checkpoint.completion)
            validate_semantic_response_identity(self.definition, response)
            self._checkpoint = identifier, body
            counts = completion_usage(checkpoint.completion, reservation)
            receipt = CoverageModelUsageReceipt(
                reservation=reservation,
                input_tokens=counts[0],
                output_tokens=counts[1],
                total_tokens=counts[2],
                checkpoint_ref=f"artifact://{identifier}",
                checkpoint_digest=sha256(body).hexdigest(),
            )
            if result.receipt is not None and result.receipt != receipt:
                raise ValueError("settled receipt conflicts with original bytes/usage")
            settle_checkpoint(
                self, receipt, body, settled=result.receipt is not None or usage_settled,
            )
            checkpoint.validate_receipt(receipt)
            derive_semantic_observation(body, receipt, self.definition, key, record)
            self._preparation_boundary()
            if self._required(identifier, MODEL_CHECKPOINT_KIND) != body:
                raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
            self._boundary()
            _validate_gateway_delegates(
                gateway, None if result.invoke and not owned_registry_data else prepared
            )
            return response
        except CoverageRefusedError:
            raise
        except Exception as error:
            raise CoverageRefusedError(Reason.UNRESOLVED_FAILURE) from error
        finally:
            if owned_registry_data is not None:
                # Strict admission requires an idle registry. Drop its single
                # unused replay preparation before GC can execute a mutated callback.
                dict.clear(owned_registry_data)
