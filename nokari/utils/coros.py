from __future__ import annotations

__all__ = ["maybe_await"]

import inspect
import typing


async def maybe_await(
    func: typing.Callable[..., typing.Any], *args: typing.Any, **kwargs: typing.Any
) -> typing.Any:
    ret = func(*args, **kwargs)
    if inspect.isawaitable(ret):
        return await ret

    return ret
