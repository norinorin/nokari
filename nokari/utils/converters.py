import re
import typing
from datetime import datetime

import hikari
import parsedatetime as pdt
import pytz
from dateutil.relativedelta import relativedelta
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
    "time_converter",
]


async def caret_converter(arg: WrappedArg) -> typing.Optional[hikari.Message]:
    ret = None

    if not arg.data:
        return arg.context.message

    if set(arg) == {"^"}:
        n = len(arg)
        try:
            ret = (
                await arg.context.bot.cache.get_messages_view()
                .iterator()
                .filter(
                    lambda m: m.created_at < arg.context.message.created_at
                    and m.channel_id == arg.context.channel_id
                )
                .reversed()
                .limit(n)
                .collect(list)
            )[n]
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


# Mostly a copy-paste from RoboDanny.

CALENDAR = pdt.Calendar(version=pdt.VERSION_CONTEXT_STYLE)
TIME_RE = re.compile(
    """(?:(?P<years>[0-9])(?:years?|y))?
       (?:(?P<months>[0-9]{1,2})(?:months?|mo))?
       (?:(?P<weeks>[0-9]{1,4})(?:weeks?|w))?
       (?:(?P<days>[0-9]{1,5})(?:days?|d))?
       (?:(?P<hours>[0-9]{1,5})(?:hours?|h))?
       (?:(?P<minutes>[0-9]{1,5})(?:minutes?|m))?
       (?:(?P<seconds>[0-9]{1,5})(?:seconds?|s))?
    """,
    re.VERBOSE,
)


def ensure_future_time(dt: datetime, now: datetime) -> None:
    if dt < now:
        raise ValueError("The argument can't be past time.")


# pylint: disable=too-many-branches
async def time_converter(arg: WrappedArg) -> typing.Tuple[datetime, str]:
    now = arg.context.message.created_at

    if (match := TIME_RE.match(arg.data)) is not None and match.group(0):
        data = {k: int(v) for k, v in match.groupdict(default="0").items()}
        remaining = arg.data[match.end() :].strip()
        dt = now + relativedelta(**data)  # type: ignore
        ensure_future_time(dt, now)
        return dt, remaining

    if arg.data.endswith("from now"):
        arg.data = arg.data[:-8].strip()

    if arg.data.startswith(("me to ", "me in ", "me at ")):
        arg.data = arg.data[6:]

    exc = ValueError('Invalid time provided, try e.g. "next week" or "2 days".')

    if (elements := CALENDAR.nlp(arg.data, sourceTime=now)) is None or len(
        elements
    ) == 0:
        raise exc

    n_dt, status, begin, end, _ = elements[0]

    dt = pytz.UTC.localize(n_dt)  # pylint: disable=no-value-for-parameter

    if not status.hasDateOrTime:
        raise exc

    if begin not in (0, 1) and end != len(arg.data):
        raise ValueError(
            "The time must be either in the beginning or end of the argument."
        )

    if not status.hasTime:
        dt = dt.replace(
            hour=now.hour,
            minute=now.minute,
            second=now.second,
            microsecond=now.microsecond,
        )

    if status.accuracy == pdt.pdtContext.ACU_HALFDAY:
        dt = dt.replace(day=now.day + 1)

    ensure_future_time(dt, now)

    if begin in (0, 1):
        if begin == 1:
            # check if it's quoted:
            if arg.data[0] != '"':
                raise ValueError("Expected quote before time input...")

            if not (end < len(arg.data) and arg.data[end] == '"'):
                raise ValueError("Expected closing quote...")

            remaining = arg.data[end + 1 :].lstrip(" ,.!")
        else:
            remaining = arg.data[end:].lstrip(" ,.!")
    elif len(arg.data) == end:
        remaining = arg.data[:begin].strip()

    return dt, remaining
