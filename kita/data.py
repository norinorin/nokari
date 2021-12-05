__all__ = ["data", "DataContainerMixin"]

import inspect
import typing as t

from hikari.undefined import UNDEFINED, UndefinedOr
from topgg.errors import TopGGException

from kita.typedefs import ICommandCallback

T = t.TypeVar("T")
DataContainerT = t.TypeVar("DataContainerT", bound="DataContainerMixin")


# this is meant to be a singleton,
# but we don't care if it's instantiated more than once
# we'll only use the one we instantiated here: _UNSET.
class _UnsetType:
    def __bool__(self) -> bool:
        return False


_UNSET = _UnsetType()
EMPTY_DICT: t.MutableMapping[t.Type, t.Any] = {}


def data(type_: t.Type[T]) -> T:
    return t.cast(T, Data(type_))


class Data(t.Generic[T]):
    __slots__ = ("type",)

    def __init__(self, type_: t.Type[T]) -> None:
        self.type: t.Type[T] = type_


class DataContainerMixin:
    __slots__ = ("_data", "_lookup_cache")

    def __init__(self) -> None:
        self._data: t.Dict[t.Type, t.Any] = {type(self): self}
        self._lookup_cache: t.Dict[t.Type, t.Any] = {}

    def set_data(
        self: DataContainerT, data_: t.Any, *, override: bool = False
    ) -> DataContainerT:
        type_ = type(data_)
        if not override and type_ in self._data:
            raise TopGGException(f"{type_} already exists.")

        # exclude the type itself and object
        for sup in type_.mro()[1:-1]:
            if sup in self._lookup_cache:
                self._lookup_cache[sup] = data_

        self._data[type_] = data_
        return self

    @t.overload
    def get_data(self, type_: t.Type[T]) -> t.Optional[T]:
        ...

    @t.overload
    def get_data(self, type_: t.Type[T], default: t.Any = None) -> t.Any:
        ...

    def get_data(self, type_: t.Any, default: t.Any = None) -> t.Any:
        """Gets the injected data."""
        try:
            return self._get_data(type_, {})
        except LookupError:
            return default

    async def _invoke_callback(
        self,
        callback: ICommandCallback,
        *args: t.Any,
        extra_env: UndefinedOr[t.MutableMapping[t.Type, t.Any]] = UNDEFINED,
        **kwargs: t.Any,
    ) -> T:
        signatures: t.Dict[str, Data] = {
            k: v.default
            for k, v in callback.__signature__.parameters.items()
            if v.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            and isinstance(v.default, Data)
        }

        for k, v in signatures.items():
            signatures[k] = self._get_data(v.type, extra_env or EMPTY_DICT)

        res = callback(*args, **{**signatures, **kwargs})
        if inspect.isawaitable(res):
            return await res

        return res

    def _resolve_data(
        self, type_: t.Type[T], env: t.MutableMapping[t.Type, t.Any]
    ) -> t.Union[_UnsetType, t.Tuple[bool, T]]:
        maybe_data = {**self._data, **env}.get(type_, _UNSET)
        if maybe_data is not _UNSET:
            return False, maybe_data

        cache = self._lookup_cache.get(type_, _UNSET)
        if cache is not _UNSET:
            return False, cache

        for subclass in type_.__subclasses__():
            maybe_data = self._resolve_data(subclass, env)
            if maybe_data is not _UNSET:
                return True, maybe_data[1]

        return _UNSET

    def _get_data(self, type_: t.Type[T], env: t.MutableMapping[t.Type, t.Any]) -> T:
        maybe_data = self._resolve_data(type_, env)

        if maybe_data is _UNSET:
            raise LookupError(f"data of type {type_} can't be found.")

        assert isinstance(maybe_data, tuple)
        is_subclass, data_ = maybe_data
        if is_subclass:
            self._lookup_cache[type_] = data_

        return data_
