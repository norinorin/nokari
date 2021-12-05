import inspect
import typing as t

from hikari.commands import CommandOption, OptionType
from hikari.impl.special_endpoints import CommandBuilder

from kita.typedefs import ICommandCallback, IGroupCommandCallback

__all__ = ("get_command_builder", "ensure_signature")


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


def ensure_signature(callback: ICommandCallback) -> None:
    if not hasattr(callback, "options"):
        callback.options = []

    if not hasattr(callback, "__signature__"):
        callback.__signature__ = inspect.signature(callback)
