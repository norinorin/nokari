"""A module that contains custom command class and decorator implementations."""
from __future__ import annotations

import logging
import os
import typing

from lightbulb import commands, context

__all__: typing.Final[typing.List[str]] = ["CommandLike", "command"]
_LOGGER = logging.getLogger("nokari.core.commands")


class CommandLike(commands.CommandLike):
    """Custom command-like class with extra attributes."""

    def __init__(
        self,
        *args: typing.Any,
        disabled: bool = False,
        signature: str | None = None,
        **kwargs: typing.Any,
    ) -> None:
        self.disabled = disabled
        self.signature = signature
        super().__init__(*args, **kwargs)


def command(
    name: str,
    description: str,
    required_vars: typing.Iterable[str] = (),
    **kwargs: typing.Any,
) -> typing.Callable[
    [
        typing.Callable[
            [context.base.Context], typing.Coroutine[typing.Any, typing.Any, None]
        ]
    ],
    CommandLike,
]:
    """
    A custom decorator that takes arbitrary kwargs and passes it
    when instantiating the Command object.
    """

    def decorate(
        func: typing.Callable[
            [context.base.Context], typing.Coroutine[typing.Any, typing.Any, None]
        ]
    ) -> commands.base.CommandLike:
        if missing := [var for var in required_vars if var not in os.environ]:
            _LOGGER.warning(
                "Missing %s env variable%s. %s will be disabled",
                ", ".join(missing),
                "s" * bool(missing),
                name,
            )

        return CommandLike(func, name, description, disabled=bool(missing), **kwargs)

    return decorate
