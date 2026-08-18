"""Shared errors for PostgreSQL Memory delivery boundaries."""


class MemoryDeliveryConflictError(ValueError):
    """A delivery CAS, scope generation or idempotency boundary was lost."""
