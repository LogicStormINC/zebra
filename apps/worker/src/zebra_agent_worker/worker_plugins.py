"""Frozen package recovery and bounded checks of only the admitted source union."""

import asyncio
from concurrent.futures import CancelledError
from dataclasses import dataclass

from agent_core.application.plugin_component_ownership import managed_skill_ids
from agent_core.application.plugin_resolution import PluginPackageReader
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_core.domain.plugin_installations import PluginInstallation, PluginSkillBinding
from agent_core.domain.plugin_snapshots import PluginSnapshot
from agent_core.ports.plugin_installations import PluginInstallationStore

from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.extension_recovery import RecoveredTurnExtension


@dataclass(frozen=True)
class WorkerPluginSource:
    installations: PluginInstallationStore
    packages: PluginPackageReader | None


@dataclass(frozen=True)
class WorkerPluginGuard:
    source: WorkerPluginSource
    extension: RecoveredTurnExtension
    frozen: tuple[PluginInstallation, ...]

    def _required(self) -> set[tuple[str, str]]:
        snapshot = self.extension.snapshot
        return (
            {("skill-bundle", s.installation_id) for s in snapshot.skills}
            | {("mcp-http", m.connection.connection_id) for m in snapshot.mcp}
        ) - (
            {("skill-bundle", s) for s in snapshot.direct_skills}
            | {("mcp-http", m) for m in snapshot.direct_mcp}
        )

    async def current(self) -> tuple[PluginInstallation, ...]:
        identifiers = tuple(
            p.installation_id
            for p in self.extension.snapshot.plugins
            if any((c.kind, c.target_id) in self._required() for c in p.components)
        )
        if not identifiers:
            return ()
        return await self.source.installations.get_current_batch(
            scope=self.extension.scope, installation_ids=identifiers
        )

    def _covered(self, records: tuple[PluginInstallation, ...]) -> bool:
        snapshot = self.extension.snapshot
        pins = {p.installation_id: p for p in snapshot.plugins}
        skills = {s.installation_id: s for s in snapshot.skills}
        mcp = {m.connection.connection_id: m for m in snapshot.mcp}
        covered: set[tuple[str, str]] = set()
        for record in records:
            pin = pins.get(record.installation_id)
            if (
                record.scope != self.extension.scope
                or not record.enabled
                or PluginSnapshot.from_installation(record) != pin
            ):
                continue
            valid = all(
                skills.get(b.installation.installation_id) == b.installation
                if isinstance(b, PluginSkillBinding)
                else (
                    b.connection.connection_id in mcp
                    and mcp[b.connection.connection_id].connection == b.connection
                    and mcp[b.connection.connection_id].catalog_digest == b.catalog_digest
                )
                for b in record.bindings
            )
            if valid and pin is not None:
                covered.update((c.kind, c.target_id) for c in pin.components)
        return self._required() <= covered

    def validate(self) -> None:
        try:
            records = asyncio.run(self.current())
            trusted = tuple(record for record in records if record in self.frozen)
            if not self._covered(trusted):
                raise PluginAuthorityUnavailable()
        except (CancelledError, LeaseLostError, ExecutionInterrupted):
            raise
        except Exception as exc:
            raise PluginAuthorityUnavailable("accepted plugin source is unavailable") from exc


def prepare_worker_plugins(
    extension: RecoveredTurnExtension | None,
    *,
    source: WorkerPluginSource | None,
    skills_available: bool,
    mcp_available: bool,
) -> WorkerPluginGuard | None:
    if extension is None:
        return None
    snapshot = extension.snapshot
    direct = tuple(
        skill for skill in snapshot.skills
        if not snapshot.plugins or skill.installation_id in snapshot.direct_skills
    )
    if direct and source is None:
        raise PluginAuthorityUnavailable("accepted Skill ownership reader is unavailable")
    try:
        if asyncio.run(managed_skill_ids(
            source.installations if source is not None else None, extension.scope, direct
        )):
            raise PluginAuthorityUnavailable("package-managed Skill has no accepted Plugin origin")
    except (CancelledError, LeaseLostError, ExecutionInterrupted):
        raise
    except Exception as exc:
        raise PluginAuthorityUnavailable("accepted Skill origin is unavailable") from exc
    if not snapshot.plugins:
        return None
    if (
        source is None
        or source.packages is None
        or (extension.snapshot.skills and not skills_available)
        or (extension.snapshot.mcp and not mcp_available)
    ):
        raise PluginAuthorityUnavailable("selected plugin component Worker source is unavailable")

    async def recover() -> WorkerPluginGuard:
        assert source.packages is not None
        initial = WorkerPluginGuard(source, extension, ())
        current = {record.installation_id: record for record in await initial.current()}
        verified: list[PluginInstallation] = []
        for pin in extension.snapshot.plugins:
            if not any((c.kind, c.target_id) in initial._required() for c in pin.components):
                continue
            try:
                exact = await source.installations.get_revision(
                    scope=extension.scope,
                    installation_id=pin.installation_id,
                    revision=pin.revision,
                )
                if (
                    exact.scope != extension.scope
                    or current.get(pin.installation_id) != exact
                    or PluginSnapshot.from_installation(exact) != pin
                ):
                    continue
                await source.packages.read(exact.package)
                verified.append(exact)
            except (CancelledError, LeaseLostError, ExecutionInterrupted):
                raise
            except Exception:
                # A redundant unavailable source must not revoke an independent origin.
                continue
        if not initial._covered(tuple(verified)):
            raise PluginAuthorityUnavailable("accepted plugin sources cannot be recovered")
        return WorkerPluginGuard(source, extension, tuple(verified))

    try:
        return asyncio.run(recover())
    except (CancelledError, LeaseLostError, ExecutionInterrupted):
        raise
    except Exception as exc:
        raise PluginAuthorityUnavailable("accepted plugin sources cannot be recovered") from exc
