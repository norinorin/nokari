from __future__ import annotations

import typing as t

from hikari.channels import ChannelType
from hikari.commands import CommandChoice, CommandOption, OptionType
from hikari.undefined import UNDEFINED, UndefinedOr

from kita.typedefs import ICommandCallback
from kita.utils import ensure_signature

__all__ = ("option",)


def option(
    type: OptionType,
    name: str,
    description: str,
    required: UndefinedOr[bool] = UNDEFINED,
    choices: UndefinedOr[t.Sequence[CommandChoice]] = UNDEFINED,
    channel_types: UndefinedOr[t.Sequence[t.Union[ChannelType, int]]] = UNDEFINED,
) -> t.Callable[[ICommandCallback], ICommandCallback]:
    def decorator(func: ICommandCallback) -> ICommandCallback:
        ensure_signature(func)
        if name not in func.__code__.co_varnames:
            return func

        func.options.insert(
            0,
            CommandOption(
                type=type,
                name=name,
                description=description,
                is_required=required if required is not UNDEFINED else True,
                choices=choices or None,
                channel_types=channel_types or None,
            ),
        )
        return func

    return decorator
