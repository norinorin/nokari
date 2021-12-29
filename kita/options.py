from __future__ import annotations

from inspect import Signature
from typing import Callable, Sequence, Union, cast

from hikari.channels import ChannelType
from hikari.commands import CommandChoice, CommandOption, OptionType
from hikari.undefined import UNDEFINED, UndefinedOr

from kita.typedefs import CallableProto, ICommandCallback
from kita.utils import ensure_options, ensure_signature

__all__ = ("with_option",)


def with_option(
    type_: OptionType,
    name: str,
    description: str,
    choices: UndefinedOr[Sequence[CommandChoice]] = UNDEFINED,
    channel_types: UndefinedOr[Sequence[Union[ChannelType, int]]] = UNDEFINED,
) -> Callable[[CallableProto], ICommandCallback]:
    def decorator(func: CallableProto) -> ICommandCallback:
        cast_func = cast(ICommandCallback, func)
        ensure_signature(cast_func)
        ensure_options(cast_func)
        if name not in cast_func.__code__.co_varnames:
            return cast_func

        cast_func.options.insert(
            0,
            CommandOption(
                type=type_,
                name=name,
                description=description,
                is_required=cast_func.__signature__.parameters[name].default
                is Signature.empty,
                choices=choices or None,
                channel_types=channel_types or None,
            ),
        )
        return cast_func

    return decorator
