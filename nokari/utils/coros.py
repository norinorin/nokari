__all__ = ["maybe_await"]

import inspect
import typing

R = typing.TypeVar("R")


class MaybeCoroutine(typing.Protocol[R]):
    def __call__(
        self, *args: typing.Any, **kwargs: typing.Any
    ) -> typing.Union[R, typing.Awaitable[R]]:
        ...


async def maybe_await(
    func: MaybeCoroutine[R], *args: typing.Any, **kwargs: typing.Any
) -> R:
    ret = func(*args, **kwargs)

    if inspect.isawaitable(ret):
        return await ret
    return ret
