"""One native deadline across command proof, preparation and mutation phases."""

from collections.abc import Callable
from functools import wraps
from time import monotonic

from agent_storage.postgres.task_io import task_io_deadline


def command_read_budget[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    @wraps(operation)
    def bounded(*args: P.args, **kwargs: P.kwargs) -> R:
        result: R | None = None
        try:
            with task_io_deadline(monotonic() + 2):
                result = operation(*args, **kwargs)
            return result
        except TimeoutError:
            # A completed preparation-only return carries no canonical writes.
            # Preserve its retryable status if the scope's exit check expires.
            # Never turn a mutation/unknown COMMIT timeout into PREPARING.
            if result is not None and getattr(result, "status", None) == "preparing":
                return result
            raise

    return bounded
