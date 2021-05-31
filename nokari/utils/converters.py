import typing

import hikari
from lightbulb import utils
from lightbulb.converters import WrappedArg
from lightbulb.converters import member_converter as member_converter_
from lightbulb.converters import user_converter as user_converter_
from lightbulb.errors import ConverterFailure
from lru import LRU  # pylint: disable=no-name-in-module

__all__: typing.Final[typing.List[str]] = [
    "user_converter",
    "member_converter",
    "caret_converter",
]


async def caret_converter(arg: WrappedArg) -> typing.Optional[hikari.Message]:
    ret = None

    if not arg.data:
        return arg.context.message

    if set(arg) == {"^"}:
        n = len(arg)
        try:
            ret = [
                i
                for i in arg.context.bot.cache.get_messages_view().iterator()
                if i.created_at < arg.context.message.created_at
                and i.channel_id == arg.context.channel_id
            ][-n]
        except IndexError:
            ret = await (
                arg.context.channel.history(before=arg.context.message_id)
                .limit(n)
                .last()
            )

    return ret


async def user_converter(arg: WrappedArg) -> hikari.User:
    msg = await caret_converter(arg)
    if msg is not None:
        return msg.author

    return await user_converter_(arg)  # pylint: disable=abstract-class-instantiated


_member_cache = LRU(50)


def _update_cache(members: typing.Iterable[hikari.Member]) -> None:
    _member_cache.update(
        **{f"{member.guild_id}:{member.id}": member for member in members}
    )


async def search_member(
    app: hikari.BotApp, guild_id: int, name: str
) -> typing.Optional[hikari.Member]:
    members = _member_cache.values()
    username, _, discriminator = name.rpartition("#")
    valid_discriminator = username and len(discriminator) == 4
    name = username if valid_discriminator else name

    for i in range(2):
        if valid_discriminator and (
            member := utils.get(members, username=name, discriminator=discriminator)
        ):
            return member

        if not valid_discriminator and (
            member := utils.find(members, lambda m: name in (m.username, m.nickname))
        ):
            return member

        if not i:
            members = await app.rest.search_members(guild_id, name=name)
            _update_cache(members)

    return None


async def member_converter(arg: WrappedArg) -> hikari.Member:
    msg = await caret_converter(arg)
    if msg is not None:
        if msg.member is not None:
            return msg.member

        if (member := arg.context.guild.get_member(msg.author.id)) is not None:
            return member

    if member := _member_cache.get(f'{arg.context.guild_id}:{arg.data.strip("<@!>")}'):
        return member

    try:
        member = await member_converter_(arg)
        _member_cache[f"{member.guild_id}:{member.id}"] = member
        return member
    except ConverterFailure:
        member = await search_member(arg.context.bot, arg.context.guild_id, arg.data)
        if not member:
            raise

        return member
