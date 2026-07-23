from pathlib import Path

from agent_storage import (
    ControlPlaneStores,
    require_legacy_database_coherence,
    sqlite_control_plane_stores,
)


class ControlPlaneStorageMixin:
    """Lazily expose one control-plane store bundle to API mixins."""

    database_path: Path
    _stores: ControlPlaneStores | None

    def __post_init__(self) -> None:
        if self._stores is not None:
            require_legacy_database_coherence(self._stores, self.database_path)

    @property
    def stores(self) -> ControlPlaneStores:
        stores = self._stores or sqlite_control_plane_stores(self.database_path)
        object.__setattr__(self, "_stores", stores)
        return stores

    @stores.setter
    def stores(self, value: ControlPlaneStores) -> None:
        # ponytail: the setter satisfies writable mixin contracts; the frozen API
        # still blocks ordinary reassignment.
        object.__setattr__(self, "_stores", value)
