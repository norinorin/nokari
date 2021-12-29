from functools import partial
from typing import Callable, MutableMapping, Set, TypeVar, Union, cast

from hikari.commands import OptionType
from hikari.snowflakes import Snowflakeish
from hikari.undefined import UNDEFINED, UndefinedOr

from kita.typedefs import (
    CallableProto,
    CommandCallback,
    ICommandCallback,
    IGroupCommandCallback,
    SubCommandCallback,
    SubCommandGroupCallback,
)
from kita.utils import (
    ensure_bucket_manager,
    ensure_checks,
    ensure_options,
    ensure_signature,
)

__all__ = ("command",)
_CallbackT = TypeVar("_CallbackT", bound=ICommandCallback)


def command(
    name: str,
    description: str,
    guild_ids: UndefinedOr[Set[Snowflakeish]] = UNDEFINED,
) -> Callable[[CallableProto], CommandCallback]:
    def decorator(func: CallableProto) -> CommandCallback:
        cast_func = cast(CommandCallback, func)
        _set_metadata(cast_func, name, description)
        _init_callback(cast_func)
        cast_func.__guild_ids__ = guild_ids or set()
        return cast_func

    return decorator


def _set_metadata(
    func: _CallbackT,
    name: str,
    description: str,
    type_: UndefinedOr[OptionType] = UNDEFINED,
) -> _CallbackT:
    func.__name__ = name
    func.__description__ = description
    func.__type__ = type_
    func.__is_command__ = True
    ensure_signature(func)
    ensure_options(func)
    ensure_checks(func)
    ensure_bucket_manager(func)
    return func


def _init_callback(func: CommandCallback) -> None:
    __sub_commands__: MutableMapping[
        str, Union[SubCommandCallback, SubCommandGroupCallback]
    ] = {}

    def command_(
        self: IGroupCommandCallback, name: str, description: str
    ) -> Callable[[CallableProto], SubCommandCallback]:
        def decorator(_func: CallableProto) -> SubCommandCallback:
            cast_func = cast(SubCommandCallback, _func)
            _set_metadata(cast_func, name, description, OptionType.SUB_COMMAND)
            self.__sub_commands__[name] = cast_func
            return cast_func

        return decorator

    def group(
        name: str, description: str
    ) -> Callable[[CallableProto], IGroupCommandCallback]:
        def decorator(_func: CallableProto) -> IGroupCommandCallback:
            cast_func = cast(IGroupCommandCallback, _func)
            _set_metadata(cast_func, name, description, OptionType.SUB_COMMAND_GROUP)
            __sub_commands__[name] = cast_func
            cast_func.command = partial(command_, cast_func)  # type: ignore
            cast_func.__sub_commands__ = {}
            return cast_func

        return decorator

    func.__sub_commands__ = __sub_commands__
    func.command = partial(command_, func)  # type: ignore
    func.group = group  # type: ignore
