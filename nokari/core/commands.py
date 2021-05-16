"""A module that contains custom command class and decorator implementations."""

import typing

from lightbulb import commands

__all__: typing.Final[typing.List[str]] = ["Command", "command", "group"]


class Command(commands.Command):
    """Custom class command with extra attributes."""

    def __init__(
        self,
        *args: typing.Any,
        usage: typing.Optional[str] = None,
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.usage = usage
        """The custom command signature if specified."""


_CommandCallbackT = typing.TypeVar(
    "_CommandCallbackT", bound=typing.Callable[..., typing.Any]
)


def command(
    name: typing.Optional[str] = None,
    cls: typing.Type[commands.Command] = Command,
    allow_extra_arguments: bool = True,
    aliases: typing.Optional[typing.Sequence[str]] = None,
    hidden: bool = False,
    **kwargs: typing.Any,
) -> typing.Callable[[_CommandCallbackT], _CommandCallbackT]:
    """
    A custom decorator that takes arbitrary kwargs and passes it
    when instantiating the Command object.
    """

    def decorate(func: _CommandCallbackT) -> commands.Command:
        return cls(
            func,
            name or func.__name__,
            allow_extra_arguments,
            aliases or [],
            hidden,
            **kwargs,
        )

    return decorate


group = commands.group  # re-export
