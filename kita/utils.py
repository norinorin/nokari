import inspect
import typing as t
from types import TracebackType

from hikari.commands import CommandOption, OptionType
from hikari.impl.special_endpoints import CommandBuilder

from kita.typedefs import ICommandCallback, IGroupCommandCallback, SignatureAware

__all__ = ("get_command_builder", "ensure_signature", "ensure_options", "find")
T = t.TypeVar("T")


def get_options(callback: ICommandCallback) -> t.List[CommandOption]:
    if not hasattr(callback, "__sub_commands__"):
        return callback.options

    callback = t.cast(IGroupCommandCallback, callback)

    return [
        CommandOption(
            type=t.cast(OptionType, sub_command.__type__),
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


def ensure_signature(callback: SignatureAware) -> None:
    if not hasattr(callback, "__signature__"):
        callback.__signature__ = inspect.signature(callback)


def ensure_options(callback: ICommandCallback) -> None:
    if not hasattr(callback, "options"):
        callback.options = []


def find(predicate: t.Callable[[T], bool], iterable: t.Iterable[T]) -> t.Optional[T]:
    for item in iterable:
        if predicate(item):
            return item
    else:
        return None


def get_exc_info(
    exception: BaseException,
) -> t.Tuple[t.Type[BaseException], BaseException, t.Optional[TracebackType]]:
    return type(exception), exception, exception.__traceback__
