"""Filter current product authority before returning catalog pages or cursors."""

from agent_core.domain.extensions import ExtensionScope
from agent_core.ports.extensions import ExtensionPageRequest, ExtensionRevisionConflictError
from agent_core.ports.plugin_installations import (
    PluginDistributionReader,
    PluginPackageCatalogPage,
    PluginPackagePublisher,
)


async def plugin_catalog(
    publisher: PluginPackagePublisher,
    distribution: PluginDistributionReader | None,
    scope: ExtensionScope,
    page: ExtensionPageRequest,
) -> PluginPackageCatalogPage:
    if distribution is None:
        return await publisher.list_packages(page=page)
    if page.cursor is not None:
        await distribution.resolve(scope=scope, package_digest=page.cursor)
    visible = []
    cursor = page.cursor
    limit = min(page.limit, 10)
    # ponytail: bounded scan of <=128 configured packages; a larger catalog needs
    # a current-authorized manifest index, never a hidden-digest pagination cursor.
    for _ in range(14):
        candidates = await publisher.list_packages(
            page=ExtensionPageRequest(limit=10, cursor=cursor)
        )
        for entry in candidates.items:
            try:
                await distribution.resolve(scope=scope, package_digest=entry.package_digest)
            except ExtensionRevisionConflictError:
                continue
            visible.append(entry)
            if len(visible) > limit:
                return PluginPackageCatalogPage(
                    items=tuple(visible[:limit]), next_cursor=visible[limit - 1].package_digest
                )
        if candidates.next_cursor is None:
            return PluginPackageCatalogPage(items=tuple(visible))
        cursor = candidates.next_cursor
    raise RuntimeError("bounded current catalog unavailable")
