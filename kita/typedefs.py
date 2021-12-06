from __future__ import annotations

import inspect
import typing as t
from importlib.machinery import ModuleSpec
from types import CodeType

from hikari.api.event_manager import EventT
from hikari.commands import CommandOption, OptionType
from hikari.snowflakes import Snowflakeish
from hikari.undefined import UndefinedOr

if t.TYPE_CHECKING:
    from importlib.abc import _LoaderProtocol

    from kita.command_handlers import GatewayCommandHandler

__all__ = (
    "CommandCallback",
    "CommandContainer",
    "OptionAware",
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
)
T = t.TypeVar("T")


class OptionAware(t.Protocol):
    options: t.List[CommandOption]


class Callable(t.Protocol):
    __call__: t.Callable[..., t.Any]


class SignatureAware(Callable, t.Protocol):
    __signature__: inspect.Signature


class ICommandCallback(OptionAware, SignatureAware, t.Protocol):
    __type__: UndefinedOr[OptionType]
    __name__: str
    __description__: str
    __code__: CodeType
    __is_command__: t.Literal[True]


class IGroupCommandCallback(ICommandCallback, t.Protocol):
    __sub_commands__: t.MutableMapping[str, ICommandCallback]

    @staticmethod
    def command(
        name: str, description: str
    ) -> t.Callable[[Callable], SubCommandCallback]:
        ...


class CommandCallback(IGroupCommandCallback, t.Protocol):
    __guild_ids__: t.Set[Snowflakeish]

    @staticmethod
    def group(
        name: str, description: str
    ) -> t.Callable[[Callable], SubCommandGroupCallback]:
        ...


class SubCommandCallback(ICommandCallback, t.Protocol):
    ...


class SubCommandGroupCallback(IGroupCommandCallback, t.Protocol):
    __sub_commands__: t.MutableMapping[str, SubCommandCallback]


CommandContainer = t.MutableMapping[str, CommandCallback]


class Extension(t.Protocol):
    __name__: str
    __file__: t.Optional[str]
    __dict__: t.Dict[str, t.Any]
    __loader__: t.Optional[_LoaderProtocol]
    __package__: t.Optional[str]
    __path__: t.MutableSequence[str]
    __spec__: t.Optional[ModuleSpec]
    __einit__: ExtensionInitializer
    __edel__: ExtensionFinalizer


class _ExtensionCallback(t.Protocol):
    def __call__(self, handler: GatewayCommandHandler) -> t.Any:
        ...


class _ExtensionCallbackWithData(t.Protocol):
    def __call__(
        self, handler: GatewayCommandHandler, *args: t.Any, **kwargs: t.Any
    ) -> t.Any:
        ...


IExtensionCallback = t.Union[_ExtensionCallback, _ExtensionCallbackWithData]


class ExtensionInitializer(t.Protocol):
    __name__: t.Literal["__einit__"]
    __call__: IExtensionCallback


class ExtensionFinalizer(t.Protocol):
    __name__: t.Literal["__edel__"]
    __call__: IExtensionCallback


class _IEventCallback(SignatureAware, t.Protocol[EventT]):
    __etype__: t.Type[EventT]
    __is_listener__: t.Literal[True]


class _EventCallback(_IEventCallback[EventT], t.Protocol):
    async def call(self, event: EventT) -> t.Any:
        ...


class _EventCallbackWithData(_IEventCallback[EventT], t.Protocol):
    async def call(self, event: EventT, *args: t.Any, **kwargs: t.Any) -> t.Any:
        ...


EventCallback = t.Union[_EventCallback[EventT], _EventCallbackWithData[EventT]]
