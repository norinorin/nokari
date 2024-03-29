import inspect
from typing import (
    Any,
    Dict,
    Generic,
    MutableMapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from hikari.undefined import UNDEFINED, UndefinedOr

from kita.typedefs import CallableT
from kita.utils import ensure_signature

__all__ = ("data", "DataContainerMixin")
T_co = TypeVar("T_co", covariant=True)
DataContainerT = TypeVar("DataContainerT", bound="DataContainerMixin")


# this is meant to be a singleton,
# but we don't care if it's instantiated more than once
# we'll only use the one we instantiated here: _UNSET.
class _UnsetType:
    def __bool__(self) -> bool:
        return False


_UNSET = _UnsetType()
EMPTY_DICT: MutableMapping[Type, Any] = {}


def data(type_: Type[T_co]) -> T_co:
    return cast(T_co, Data(type_))


class Data(Generic[T_co]):
    __slots__ = ("type",)

    def __init__(self, type_: Type[T_co]) -> None:
        self.type: Type[T_co] = type_


class DataContainerMixin:
    __slots__ = ("_data", "_lookup_cache")

    def __init__(self) -> None:
        self._data: Dict[Type, Any] = {type(self): self}
        self._lookup_cache: Dict[Type, Any] = {}

    def set_data(
        self: DataContainerT,
        data_: Any,
        *,
        override: bool = False,
        suppress: bool = False,
    ) -> DataContainerT:
        type_ = type(data_)
        if not override and type_ in self._data:
            if not suppress:
                raise RuntimeError(f"{type_} already exists.")
            return self

        # exclude the type itself and object
        for sup in type_.mro()[1:-1]:
            if sup in self._lookup_cache:
                self._lookup_cache[sup] = data_

        self._data[type_] = data_
        return self

    @overload
    def get_data(self, type_: Type[T_co]) -> Optional[T_co]:
        ...

    @overload
    def get_data(self, type_: Type[T_co], default: Any = None) -> Any:
        ...

    def get_data(self, type_: Any, default: Any = None) -> Any:
        """Gets the injected data."""
        try:
            return self._get_data(type_, {})
        except LookupError:
            return default

    async def _invoke_callback(
        self,
        callback: CallableT[T_co],
        *args: Any,
        extra_env: UndefinedOr[MutableMapping[Type, Any]] = UNDEFINED,
        **kwargs: Any,
    ) -> T_co:
        callback = ensure_signature(callback)
        signatures: Dict[str, Data] = {
            k: v.default
            for k, v in callback.__signature__.parameters.items()
            if v.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            and isinstance(v.default, Data)
        }

        for k, v in signatures.items():
            signatures[k] = self._get_data(
                v.type, extra_env if extra_env is not UNDEFINED else EMPTY_DICT
            )

        res = callback(*args, **{**signatures, **kwargs})
        if inspect.isawaitable(res):
            return await res

        return res

    def _resolve_data(
        self, type_: Type[T_co], env: MutableMapping[Type, Any]
    ) -> Union[_UnsetType, Tuple[bool, T_co]]:
        maybe_data = {**self._data, **env}.get(type_, _UNSET)
        if maybe_data is not _UNSET:
            return False, maybe_data

        cache = self._lookup_cache.get(type_, _UNSET)
        if cache is not _UNSET:
            return False, cache

        for subclass in type_.__subclasses__():
            maybe_data = self._resolve_data(subclass, env)
            if maybe_data is not _UNSET:
                return not subclass in env, maybe_data[1]

        return _UNSET

    def _get_data(self, type_: Type[T_co], env: MutableMapping[Type, Any]) -> T_co:
        maybe_data = self._resolve_data(type_, env)

        if maybe_data is _UNSET:
            raise LookupError(f"data of type {type_} can't be found.")

        assert isinstance(maybe_data, tuple)
        is_subclass, data_ = maybe_data
        if is_subclass:
            self._lookup_cache[type_] = data_

        return data_
