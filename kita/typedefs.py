from __future__ import annotations

import typing as t

from hikari.commands import CommandOption, OptionType
from hikari.snowflakes import Snowflake
from hikari.undefined import UndefinedOr

__all__ = (
    "CommandCallback",
    "CommandContainer",
    "OptionAware",
    "MetadataAware",
    "ICommandCallback",
    "IGroupCommandCallback",
    "SubCommandCallback",
    "SubCommandGroupCallback",
)
T = t.TypeVar("T")


class OptionAware(t.Protocol):
    options: t.List[CommandOption]


class MetadataAware(t.Protocol):
    __type__: UndefinedOr[OptionType]
    __name__: str
    __description__: str


class ICommandCallback(OptionAware, MetadataAware, t.Protocol):
    def __call__(self, *args: t.Any, **kwargs: t.Any) -> t.Any:
        ...


class IGroupCommandCallback(ICommandCallback, t.Protocol):
    __sub_commands__: t.MutableMapping[str, ICommandCallback]

    @staticmethod
    def command(
        name: str, description: str
    ) -> t.Callable[[SubCommandCallback], SubCommandCallback]:
        ...


class CommandCallback(IGroupCommandCallback, t.Protocol):
    __guild_ids__: t.Set[Snowflake]

    @staticmethod
    def group(
        name: str, description: str
    ) -> t.Callable[[SubCommandGroupCallback], SubCommandGroupCallback]:
        ...


class SubCommandCallback(ICommandCallback, t.Protocol):
    ...


class SubCommandGroupCallback(IGroupCommandCallback, t.Protocol):
    __sub_commands__: t.MutableMapping[str, SubCommandCallback]


CommandContainer = t.MutableMapping[str, CommandCallback]
