import typing
from itertools import count

import hikari
from lightbulb.converters import WrappedArg
from lightbulb.converters import member_converter as member_converter_
from lightbulb.converters import user_converter as user_converter_


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
            history = arg.context.channel.history(before=arg.context.message_id)
            for c in count(start=1):
                ret = await history.next()
                if n == c:
                    break

    return ret


async def user_converter(arg: WrappedArg) -> hikari.User:
    msg = await caret_converter(arg)
    if msg is not None:
        return msg.author

    return await user_converter_(arg)  # pylint: disable=abstract-class-instantiated


async def member_converter(arg: WrappedArg) -> hikari.Member:
    msg = await caret_converter(arg)
    if msg is not None:
        if msg.member is not None:
            return msg.member

        if (member := arg.context.guild.get_member(msg.author.id)) is not None:
            return member

    return await member_converter_(arg)
