import typing as t
from functools import partial

from hikari.commands import OptionType
from hikari.snowflakes import Snowflake
from hikari.undefined import UNDEFINED, UndefinedOr

from kita.typedefs import (
    CommandCallback,
    ICommandCallback,
    IGroupCommandCallback,
    SubCommandCallback,
    SubCommandGroupCallback,
)

__all__ = ("command",)
_CallbackT = t.TypeVar("_CallbackT", bound=ICommandCallback)


def command(
    name: str,
    description: str,
    guild_ids: UndefinedOr[t.Set[Snowflake]] = UNDEFINED,
) -> t.Callable[[CommandCallback], CommandCallback]:
    def decorator(func: CommandCallback) -> CommandCallback:
        _set_metadata(func, name, description)
        _init_callback(func)
        func.__guild_ids__ = guild_ids or set()
        return func

    return decorator


def _set_metadata(
    func: _CallbackT,
    name: str,
    description: str,
    type: UndefinedOr[OptionType] = UNDEFINED,
) -> _CallbackT:
    func.__name__ = name
    func.__description__ = description
    func.__type__ = type
    return func


def _init_callback(func: CommandCallback) -> None:
    __sub_commands__: t.MutableMapping[
        str, t.Union[SubCommandCallback, SubCommandGroupCallback]
    ] = {}

    def command(
        self: IGroupCommandCallback, name: str, description: str
    ) -> t.Callable[[SubCommandCallback], SubCommandCallback]:
        def decorator(_func: SubCommandCallback) -> SubCommandCallback:
            _set_metadata(_func, name, description, OptionType.SUB_COMMAND)
            self.__sub_commands__[name] = _func
            return _func

        return decorator

    def group(
        name: str, description: str
    ) -> t.Callable[[SubCommandGroupCallback], SubCommandGroupCallback]:
        def decorator(_func: SubCommandGroupCallback) -> SubCommandGroupCallback:
            _set_metadata(_func, name, description, OptionType.SUB_COMMAND_GROUP)
            __sub_commands__[name] = _func
            _func.command = partial(command, _func)  # type: ignore
            _func.__sub_commands__ = {}
            return _func

        return decorator

    func.__sub_commands__ = __sub_commands__
    func.command = partial(command, func)  # type: ignore
    func.group = group  # type: ignore
