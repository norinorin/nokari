"""
A module that contains cache decorator implementations.
Based on Danny a.k.a Rapptz's implementation.
"""
import asyncio
import typing
from functools import wraps

from lru import LRU  # pylint: disable=no-name-in-module

__all__: typing.Final[typing.List[str]] = ["cache"]
_FuncT = typing.TypeVar("_FuncT", bound=typing.Callable[..., typing.Any])


def _get_key(args: typing.Tuple[typing.Any, ...]) -> str:

    _get_repr = (
        lambda obj: f"<{obj.__class__.__module__}.{obj.__class__.__name__}>"
        if obj.__class__.__repr__ is object.__repr__
        else repr(obj)
    )

    return ":".join(_get_repr(obj) for obj in args)


def cache(size: int) -> typing.Callable[[_FuncT], _FuncT]:
    def decorator(func: _FuncT) -> _FuncT:
        _is_static_method = isinstance(func, staticmethod)

        if _is_static_method:
            func = func.__get__(decorator)  # type: ignore

        _is_coro = asyncio.iscoroutinefunction(func)
        _cache = LRU(size)

        @wraps(func)
        def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            key = _get_key(args)
            if _is_static_method:
                args = args[1:]

            try:
                res = _cache[key]
            except KeyError:
                temp = func(*args, **kwargs)

                if _is_coro:

                    async def wrapper() -> typing.Coroutine:
                        res = _cache[key] = await temp
                        return res

                    return wrapper()

                res = _cache[key] = temp
            else:
                if _is_coro:
                    return asyncio.sleep(0, res)

            return res

        wrapper.cache = _cache  # type: ignore
        return typing.cast(_FuncT, wrapper)

    return decorator
