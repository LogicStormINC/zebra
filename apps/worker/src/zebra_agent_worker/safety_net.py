"""Worker safety net: bounded recovery retries and control-plane terminalization.

Production incidents (2026-10-29, ERP): a session whose recorder rejects the
event sequence fails every recovery attempt in worker setup, gets logged as
"command skipped", and is then re-picked by the ready-session scan forever —
an 11-hour "running" conversation with the worker burning CPU in a loop.

This module bounds that loop: structural recovery failures are counted in the
``agent_safety_overrides`` table; at the cap the session receives a
control-plane terminal override (dead_letter) which the loop consults before
executing, ending the retry storm. Transient failures (storage/network) are
never counted. Everything is env-flagged and ships with a shadow mode that
records what WOULD happen without changing behavior.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from agent_storage.postgres.safety_overrides import PostgresSafetyOverrideStore

logger = logging.getLogger(__name__)

_STRUCTURAL = (ValueError, TypeError)
# Recorder/integrity failures surface as text only on the command path.
_STRUCTURAL_MARKERS = ("does not match recorder", "does not match", "sequence", "integrity")


@dataclass(frozen=True, slots=True)
class SafetyNetConfig:
    enabled: bool = True
    shadow: bool = True
    dead_letter_max_attempts: int = 5

    @classmethod
    def from_env(cls, env: Callable[[str], str | None] = os.getenv) -> SafetyNetConfig:
        def flag(name: str, default: bool) -> bool:
            raw = env(name)
            return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}

        def count(name: str, default: int) -> int:
            try:
                value = int(str(env(name)).strip())
            except (TypeError, ValueError):
                return default
            return value if 1 <= value <= 100 else default

        return cls(
            enabled=flag("ZEBRA_WORKER_SAFETY_NET_ENABLED", True),
            shadow=flag("ZEBRA_WORKER_SAFETY_NET_SHADOW", True),
            dead_letter_max_attempts=count("ZEBRA_WORKER_SAFETY_NET_DEAD_LETTER_MAX_ATTEMPTS", 5),
        )


class WorkerSafetyNet:
    """Bounded-failure guard wired into the worker loop's skip paths."""

    def __init__(
        self,
        *,
        namespace: str,
        connect: Callable[[], psycopg.Connection[Any]] | None = None,
        store_context: (
            Callable[[], AbstractContextManager[PostgresSafetyOverrideStore]] | None
        ) = None,
        config: SafetyNetConfig | None = None,
    ) -> None:
        if connect is None and store_context is None:
            raise ValueError("safety net needs a connection or a store context")
        self._namespace = namespace
        self._connect = connect
        self._store_context = store_context
        self._config = config or SafetyNetConfig.from_env()

    @property
    def config(self) -> SafetyNetConfig:
        return self._config

    @contextmanager
    def _open_store(self) -> Iterator[PostgresSafetyOverrideStore]:
        if self._store_context is not None:
            with self._store_context() as store:
                yield store
            return
        assert self._connect is not None
        with self._connect() as connection:
            yield PostgresSafetyOverrideStore(connection)

    def note_recovery_failure(
        self, session_id: str, stage: str, error: BaseException | None, reason: str = ""
    ) -> None:
        """Count one skipped recovery; escalate to dead_letter at the cap."""
        if not self._config.enabled:
            return
        detail = reason or (f"{type(error).__name__}: {error}" if error is not None else stage)
        structural = isinstance(error, _STRUCTURAL) or (
            error is None and any(marker in detail for marker in _STRUCTURAL_MARKERS)
        )
        if not structural:
            # Transient blips must never dead-letter a recoverable session.
            logger.debug(
                "safety_net transient (not counted) session=%s stage=%s", session_id, stage
            )
            return
        try:
            with self._open_store() as store:
                record = store.record_failure(
                    namespace=self._namespace,
                    session_id=session_id,
                    reason=f"{stage}: {detail}",
                    structural=True,
                    max_attempts=self._config.dead_letter_max_attempts,
                    shadow=self._config.shadow,
                )
            if record.is_terminal:
                logger.error(
                    "safety_net DEAD-LETTER session=%s attempts=%s shadow=%s reason=%s",
                    session_id, record.attempts, record.shadow, record.reason,
                )
            elif record.attempts > 1:
                logger.warning(
                    "safety_net structural failure session=%s attempts=%s/%s stage=%s",
                    session_id, record.attempts, self._config.dead_letter_max_attempts, stage,
                )
        except psycopg.Error:
            # The safety net must never break the worker loop itself.
            logger.exception("safety_net storage unavailable; failure not recorded")

    def should_skip(self, session_id: str) -> bool:
        """True when a non-shadow terminal override says: stop retrying."""
        if not self._config.enabled:
            return False
        try:
            with self._open_store() as store:
                return store.terminal(namespace=self._namespace, session_id=session_id) is not None
        except psycopg.Error:
            return False  # fail open: never strand sessions because the net is down
