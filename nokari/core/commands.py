"""A module that contains a custom command class implementation."""

import typing

from lightbulb import commands


class Command(commands.Command):
    """Custom class command with extra attributes."""

    def __init__(
        self,
        *args: typing.Any,
        usage: typing.Optional[str] = None,
        **kwargs: typing.Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.usage = usage
        """The custom command signature if specified."""
