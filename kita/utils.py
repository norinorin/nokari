import inspect
from operator import attrgetter
from types import TracebackType
from typing import Any, Callable, Iterable, List, Optional, Tuple, Type, TypeVar, cast

from hikari.commands import CommandOption, OptionType
from hikari.impl.special_endpoints import CommandBuilder
from typing_extensions import TypeGuard

from kita.typedefs import (
    CallableProto,
    CommandCallback,
    EventCallback,
    ICommandCallback,
    IGroupCommandCallback,
    SignatureAware,
)

__all__ = (
    "get_command_builder",
    "ensure_signature",
    "ensure_options",
    "ensure_bucket_manager",
    "find",
    "get",
    "get_exc_info",
)
T = TypeVar("T")


def get_options(callback: ICommandCallback) -> List[CommandOption]:
    if not getattr(callback, "__sub_commands__", None):
        return callback.options

    callback = cast(IGroupCommandCallback, callback)

    return [
        CommandOption(
            type=cast(OptionType, sub_command.__type__),
            name=sub_command.__name__,
            description=sub_command.__description__,
            options=get_options(sub_command),
            is_required=False,
        )
        for sub_command in callback.__sub_commands__.values()
    ]


def get_command_builder(callback: ICommandCallback) -> CommandBuilder:
    command = CommandBuilder(
        callback.__name__, callback.__description__, get_options(callback)
    )
    return command


def ensure_signature(callback: CallableProto) -> SignatureAware:
    callback = cast(SignatureAware, callback)
    if not hasattr(callback, "__signature__"):
        callback.__signature__ = inspect.signature(callback)
    return callback


def ensure_options(callback: CallableProto) -> ICommandCallback:
    callback = cast(ICommandCallback, callback)
    callback.__dict__.setdefault("options", [])
    return callback


def ensure_checks(callback: CallableProto) -> ICommandCallback:
    callback = cast(ICommandCallback, callback)
    callback.__dict__.setdefault("__checks__", [])
    return callback


def ensure_bucket_manager(callback: Callable) -> ICommandCallback:
    callback = cast(ICommandCallback, callback)
    if not hasattr(callback, "__bucket_manager__"):
        callback.__bucket_manager__ = None
    return callback


def find(predicate: Callable[[T], bool], iterable: Iterable[T]) -> Optional[T]:
    for item in iterable:
        if predicate(item):
            return item

    return None


def get(iterable: Iterable[T], **attrs: Any) -> Optional[T]:
    _attrgetter = attrgetter
    _all = all
    getters = [(_attrgetter(attr), value) for attr, value in attrs.items()]

    for item in iterable:
        if _all(getter(item) == value for getter, value in getters):
            return item

    return None


def get_exc_info(
    exception: BaseException,
) -> Tuple[Type[BaseException], BaseException, Optional[TracebackType]]:
    return type(exception), exception, exception.__traceback__


def is_command(obj: Any) -> TypeGuard[ICommandCallback]:
    return getattr(obj, "__is_command__", False)


def is_command_parent(obj: Any) -> TypeGuard[CommandCallback]:
    return is_command(obj) and hasattr(obj, "group") and hasattr(obj, "command")


def is_listener(obj: Any) -> TypeGuard[EventCallback]:
    return getattr(obj, "__is_listener__", False)
