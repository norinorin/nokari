from __future__ import annotations

import inspect
from importlib.machinery import ModuleSpec
from types import CodeType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Literal,
    MutableMapping,
    MutableSequence,
    Optional,
    Protocol,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from hikari.api.event_manager import EventT
from hikari.commands import CommandOption, OptionType
from hikari.events.interaction_events import InteractionCreateEvent
from hikari.snowflakes import Snowflakeish
from hikari.undefined import UndefinedOr

if TYPE_CHECKING:
    from importlib.abc import _LoaderProtocol

    from kita.buckets import BucketManager
    from kita.command_handlers import GatewayCommandHandler

__all__ = (
    "CommandCallback",
    "CommandContainer",
    "OptionAware",
    "CallableProto",
    "ICommandCallback",
    "IGroupCommandCallback",
    "SubCommandCallback",
    "SubCommandGroupCallback",
    "Extension",
    "IExtensionCallback",
    "ExtensionInitializer",
    "ExtensionFinalizer",
    "EventCallback",
    "SignatureAware",
    "HashGetter",
    "LimitGetter",
    "PeriodGetter",
    "BucketHash",
)
T = TypeVar("T")


class OptionAware(Protocol):
    options: List[CommandOption]


class CallableT(Protocol[T]):
    __call__: Callable[..., T]


class CallableProto(Protocol):
    __call__: Callable[..., Any]


class SignatureAware(CallableProto, Protocol):
    __signature__: inspect.Signature


class ICommandCallback(OptionAware, SignatureAware, Protocol):
    __type__: UndefinedOr[OptionType]
    __name__: str
    __description__: str
    __code__: CodeType
    __module__: str
    __is_command__: Literal[True]
    __checks__: List[CallableProto]
    __bucket_manager__: Optional[BucketManager]


class IGroupCommandCallback(ICommandCallback, Protocol):
    __sub_commands__: MutableMapping[str, ICommandCallback]

    @staticmethod
    def command(
        name: str, description: str
    ) -> Callable[[CallableProto], SubCommandCallback]:
        ...


class CommandCallback(IGroupCommandCallback, Protocol):
    __guild_ids__: Set[Snowflakeish]

    @staticmethod
    def group(
        name: str, description: str
    ) -> Callable[[CallableProto], SubCommandGroupCallback]:
        ...


class SubCommandCallback(ICommandCallback, Protocol):
    ...


class SubCommandGroupCallback(IGroupCommandCallback, Protocol):
    __sub_commands__: MutableMapping[str, SubCommandCallback]


CommandContainer = MutableMapping[str, CommandCallback]


class Extension(Protocol):
    __name__: str
    __file__: Optional[str]
    __dict__: Dict[str, Any]
    __loader__: Optional[_LoaderProtocol]
    __package__: Optional[str]
    __path__: MutableSequence[str]
    __spec__: Optional[ModuleSpec]
    __einit__: Optional[ExtensionInitializer]
    __edel__: Optional[ExtensionFinalizer]


class IExtensionCallback(Protocol):
    def __call__(self, handler: GatewayCommandHandler) -> Any:
        ...


class ExtensionInitializer(Protocol):
    __name__: Literal["__einit__"]
    __call__: IExtensionCallback


class ExtensionFinalizer(Protocol):
    __name__: Literal["__edel__"]
    __call__: IExtensionCallback


class _IEventCallback(SignatureAware, Protocol[EventT]):
    __etype__: Type[EventT]
    __is_listener__: Literal[True]


class _EventCallback(_IEventCallback[EventT], Protocol):
    async def call(self, event: EventT) -> None:
        ...


class _EventCallbackWithData(_IEventCallback[EventT], Protocol):
    async def call(self, event: EventT, *args: Any, **kwargs: Any) -> None:
        ...


EventCallback = Union[_EventCallback[EventT], _EventCallbackWithData[EventT]]
BucketHash = Union[Snowflakeish, Tuple[Snowflakeish, ...]]


class _SyncHashGetter(CallableT[BucketHash], Protocol):
    def __call__(self, event: InteractionCreateEvent) -> BucketHash:
        ...


class _SyncHashGetterWithData(CallableT[BucketHash], Protocol):
    def __call__(
        self, event: InteractionCreateEvent, *args: Any, **kwargs: Any
    ) -> BucketHash:
        ...


class _AsyncHashGetter(CallableT[BucketHash], Protocol):
    async def __call__(self, event: InteractionCreateEvent) -> BucketHash:  # type: ignore
        ...


class _AsyncHashGetterWithData(CallableT[BucketHash], Protocol):
    async def __call__(  # type: ignore
        self, event: InteractionCreateEvent, *args: Any, **kwargs: Any
    ) -> BucketHash:
        ...


class _SyncLimitGetter(CallableT[int], Protocol):
    def __call__(self, hash: BucketHash) -> int:
        ...


class _SyncLimitGetterWithData(CallableT[int], Protocol):
    def __call__(self, hash: BucketHash, *args: Any, **kwargs: Any) -> int:
        ...


class _AsyncLimitGetter(CallableT[int], Protocol):
    async def __call__(self, hash: BucketHash) -> int:  # type: ignore
        ...


class _AsyncLimitGetterWithData(CallableT[int], Protocol):
    async def __call__(self, hash: BucketHash, *args: Any, **kwargs: Any) -> int:  # type: ignore
        ...


class _SyncPeriodGetter(CallableT[float], Protocol):
    def __call__(self, hash: BucketHash) -> float:
        ...


class _SyncPeriodGetterWithData(CallableT[float], Protocol):
    def __call__(self, hash: BucketHash, *args: Any, **kwargs: Any) -> float:
        ...


class _AsyncPeriodGetter(CallableT[float], Protocol):
    async def __call__(self, hash: BucketHash) -> float:  # type: ignore
        ...


class _AsyncPeriodGetterWithData(CallableT[float], Protocol):
    async def __call__(self, hash: BucketHash, *args: Any, **kwargs: Any) -> float:  # type: ignore
        ...


HashGetter = Union[
    _SyncHashGetter, _SyncHashGetterWithData, _AsyncHashGetter, _AsyncHashGetterWithData
]
LimitGetter = Union[
    _SyncLimitGetter,
    _SyncLimitGetterWithData,
    _AsyncLimitGetter,
    _AsyncLimitGetterWithData,
]
PeriodGetter = Union[
    _SyncPeriodGetter,
    _SyncPeriodGetterWithData,
    _AsyncPeriodGetter,
    _AsyncPeriodGetterWithData,
]
