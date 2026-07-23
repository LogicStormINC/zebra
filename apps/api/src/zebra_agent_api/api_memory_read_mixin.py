from __future__ import annotations

from pathlib import Path

from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_read import SessionReadApi


class ApiMemoryReadMixin:
    database_path: Path
    stores: ControlPlaneStores

    def get_memory_operations_overview(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_operations_overview(
            session_id,
            payload,
        )

    def get_memory_review_governance_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_review_governance_signals(
            session_id,
            payload,
        )

    def get_memory_backlog_aging_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_backlog_aging_signals(
            session_id,
            payload,
        )

    def get_memory_review_velocity_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_review_velocity_signals(
            session_id,
            payload,
        )

    def get_memory_backlog_pressure_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_backlog_pressure_signals(
            session_id,
            payload,
        )

    def get_memory_pressure_action_hints(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_pressure_action_hints(
            session_id,
            payload,
        )

    def get_memory_pressure_escalation_recommendations(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_pressure_escalation_recommendations(
            session_id,
            payload,
        )

    def get_memory_escalation_follow_up_windows(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_escalation_follow_up_windows(
            session_id,
            payload,
        )

    def get_memory_follow_up_overdue_flags(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_follow_up_overdue_flags(
            session_id,
            payload,
        )

    def get_memory_overdue_age_buckets(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_overdue_age_buckets(
            session_id,
            payload,
        )

    def get_memory_overdue_type_rollups(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_overdue_type_rollups(
            session_id,
            payload,
        )

    def get_memory_overdue_visibility_rollups(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_visibility_rollups(
            session_id,
            payload,
        )

    def get_memory_overdue_trend_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_overdue_trend_signals(
            session_id,
            payload,
        )

    def get_memory_overdue_intervention_hints(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_intervention_hints(
            session_id,
            payload,
        )

    def get_memory_overdue_escalation_lanes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_overdue_escalation_lanes(
            session_id,
            payload,
        )

    def get_memory_overdue_recovery_paths(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_overdue_recovery_paths(
            session_id,
            payload,
        )

    def get_memory_overdue_resolution_checkpoints(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_resolution_checkpoints(
            session_id,
            payload,
        )

    def get_memory_overdue_resolution_outcomes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_resolution_outcomes(
            session_id,
            payload,
        )

    def get_memory_overdue_closure_decisions(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_overdue_closure_decisions(
            session_id,
            payload,
        )

    def get_memory_overdue_archive_recommendations(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_archive_recommendations(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_guidance(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_guidance(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_windows(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_memory_overdue_retention_windows(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breaches(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breaches(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_aging(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breach_aging(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_actions(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breach_actions(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_lanes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breach_lanes(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_owner_targets(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breach_owner_targets(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_modes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breach_follow_through_modes(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_outcomes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breach_follow_through_outcomes(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_completion_states(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breach_follow_through_completion_states(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_verification_states(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breach_follow_through_verification_states(
            session_id,
            payload,
        )

    def get_memory_overdue_retention_breach_follow_through_verification_outcomes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return SessionReadApi(
            self.database_path, self.stores
        ).get_memory_overdue_retention_breach_follow_through_verification_outcomes(
            session_id,
            payload,
        )

    def get_user_memory(self, user_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_user_memory(user_id)

    def get_user_memory_queue(self, user_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_user_memory_queue(user_id)

    def get_user_memory_queue_summary(self, user_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_user_memory_queue_summary(
            user_id
        )

    def get_tenant_memory(self, tenant_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_tenant_memory(tenant_id)

    def get_tenant_memory_queue(self, tenant_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_tenant_memory_queue(tenant_id)

    def get_tenant_memory_queue_summary(self, tenant_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_tenant_memory_queue_summary(
            tenant_id
        )
