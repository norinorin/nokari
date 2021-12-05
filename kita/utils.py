from hikari.commands import CommandOption
from hikari.impl.special_endpoints import CommandBuilder

from kita.typedefs import ICommandCallback

__all__ = ("get_command_builder",)


def get_command_builder(callback: ICommandCallback) -> CommandBuilder:
    return CommandBuilder(
        callback.__name__,
        callback.__description__,
        callback.options or []
        if not (sub_commands := getattr(callback, "__sub_commands__", None))
        else [
            CommandOption(
                type=sub_command.__type__,
                name=sub_command.__name__,
                description=sub_command.__description__,
                options=sub_command.options,
                is_required=False,
            )
            for sub_command in sub_commands
        ],
    )
