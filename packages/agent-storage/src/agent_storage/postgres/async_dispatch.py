"""Optional composition-owned async dispatch for synchronous storage callbacks."""

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol


class AsyncDispatch(Protocol):
    async def __call__[T](self, action: Callable[..., T], *args: Any, **kwargs: Any) -> T: ...


_dispatch: ContextVar[AsyncDispatch | None] = ContextVar("storage_async_dispatch", default=None)


@contextmanager
def async_dispatch_scope(dispatch: AsyncDispatch | None) -> Iterator[None]:
    token = _dispatch.set(dispatch)
    try:
        yield
    finally:
        _dispatch.reset(token)


async def storage_call[T](action: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    dispatch = _dispatch.get()
    if dispatch is None:
        return await asyncio.to_thread(action, *args, **kwargs)
    return await dispatch(action, *args, **kwargs)
