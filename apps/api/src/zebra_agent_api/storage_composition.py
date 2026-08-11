from pathlib import Path

from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    compose_control_plane_stores,
)
from zebra_agent_config import ZebraAgentSettings


def resolve_api_stores(
    settings: ZebraAgentSettings,
    database_path: str | Path | None,
    stores: ControlPlaneStores | None,
    cloud: CloudCompositionSettings | None,
) -> tuple[Path, ControlPlaneStores]:
    active_path = Path(database_path or settings.database_url)
    return active_path, stores or compose_control_plane_stores(
        profile=settings.profile,
        storage_authority=settings.storage_authority,
        database_path=settings.database_url if settings.profile == "cloud" else active_path,
        cloud=cloud,
    )


class ControlPlaneStorageMixin:
    """Lazily expose one control-plane store bundle to API mixins."""

    database_path: Path
    settings: ZebraAgentSettings
    _stores: ControlPlaneStores | None

    @property
    def stores(self) -> ControlPlaneStores:
        stores = self._stores or compose_control_plane_stores(
            profile=self.settings.profile,
            storage_authority=self.settings.storage_authority,
            database_path=(
                self.settings.database_url
                if self.settings.storage_authority == "postgresql"
                else self.database_path
            ),
        )
        object.__setattr__(self, "_stores", stores)
        return stores

    @stores.setter
    def stores(self, value: ControlPlaneStores) -> None:
        # ponytail: the setter satisfies writable mixin contracts; the frozen API
        # still blocks ordinary reassignment.
        object.__setattr__(self, "_stores", value)
