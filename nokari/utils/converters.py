import re
import typing
from datetime import datetime

import hikari
import lightbulb
import parsedatetime as pdt
import pytz
from dateutil.relativedelta import relativedelta
from lightbulb import utils
from lightbulb.converters import BaseConverter
from lightbulb.errors import ConverterFailure
from lru import LRU  # pylint: disable=no-name-in-module

__all__: typing.Final[typing.List[str]] = [
    "UserConverter",
    "MemberConverter",
    "CaretConverter",
    "TimeConverter",
]


class CaretConverter(BaseConverter):
    __slots__ = ()

    async def convert(self, arg: str) -> typing.Optional[hikari.Message]:
        ret = None
        event = self.context.event
        assert isinstance(event, hikari.MessageCreateEvent)

        if not arg:
            return event.message

        if set((stripped := arg.strip())) == {"^"}:
            n = len(stripped)
            try:
                ret = typing.cast(
                    list,
                    (
                        await self.context.bot.cache.get_messages_view()
                        .iterator()
                        .filter(
                            lambda m: m.created_at < event.message.created_at
                            and m.channel_id == event.channel_id
                        )
                        .reversed()
                        .limit(n)
                        .collect(list)
                    ),
                )[n]
            except IndexError:
                channel = self.context.get_channel()
                assert isinstance(channel, hikari.GuildChannel)
                ret = await channel.fetch_history(before=msg).limit(n).last()

        return ret


class UserConverter(lightbulb.converters.UserConverter):
    __slots__ = ()

    async def convert(self, arg: str) -> hikari.User:
        if (msg := await CaretConverter(self.context).convert(arg)) is not None:
            return msg.author

        return await super().convert(arg)


_member_cache = LRU(50)


def _update_cache(members: typing.Iterable[hikari.Member]) -> None:
    _member_cache.update(
        **{f"{member.guild_id}:{member.id}": member for member in members}
    )


async def search_member(
    app: hikari.GatewayBotAware, guild_id: int, name: str
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


class MemberConverter(lightbulb.converters.MemberConverter):
    __slots__ = ()

    async def convert(self, arg: str) -> hikari.Member:
        if (msg := await CaretConverter(self.context).convert(arg)) is not None:
            if msg.member is not None:
                return msg.member

            if (member := arg.context.guild.get_member(msg.author.id)) is not None:
                return member

        if member := _member_cache.get(f'{arg.context.guild_id}:{arg.strip("<@!>")}'):
            return member

        try:
            member = await super().convert(arg)
            _member_cache[f"{member.guild_id}:{member.id}"] = member
            return member
        except ConverterFailure:
            member = await search_member(arg.context.bot, arg.context.guild_id, arg)
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


class TimeConverter(lightbulb.converters.BaseConverter[typing.Tuple[datetime, str]]):
    __slots__ = ()

    # pylint: disable=too-many-branches
    async def convert(self, arg: str) -> typing.Tuple[datetime, str]:
        now = self.context.event.message.created_at

        if (match := TIME_RE.match(arg)) is not None and match.group(0):
            data = {k: int(v) for k, v in match.groupdict(default="0").items()}
            remaining = arg[match.end() :].strip()
            dt = now + relativedelta(**data)  # type: ignore
            ensure_future_time(dt, now)
            return dt, remaining

        if arg.endswith("from now"):
            arg = arg[:-8].strip()

        if arg.startswith(("me to ", "me in ", "me at ")):
            arg = arg[6:]

        exc = ValueError('Invalid time provided, try e.g. "next week" or "2 days".')

        if (elements := CALENDAR.nlp(arg, sourceTime=now)) is None or len(
            elements
        ) == 0:
            raise exc

        n_dt, status, begin, end, _ = elements[0]

        dt = pytz.UTC.localize(n_dt)  # pylint: disable=no-value-for-parameter

        if not status.hasDateOrTime:
            raise exc

        if begin not in (0, 1) and end != len(arg):
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
                if arg[0] != '"':
                    raise ValueError("Expected quote before time input...")

                if not (end < len(arg) and arg[end] == '"'):
                    raise ValueError("Expected closing quote...")

                remaining = arg[end + 1 :].lstrip(" ,.!")
            else:
                remaining = arg[end:].lstrip(" ,.!")
        elif len(arg) == end:
            remaining = arg[:begin].strip()

        return dt, remaining
