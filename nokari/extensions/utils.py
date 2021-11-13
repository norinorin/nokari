# Reminders based on RoboDanny.

import asyncio
import logging
import textwrap
import typing
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from itertools import zip_longest

import asyncpg
import hikari
import lightbulb
from hikari.snowflakes import Snowflake
from lightbulb import BotApp, Plugin
from tabulate import tabulate

from nokari import core
from nokari.core.context import Context
from nokari.utils import db, plural, timers
from nokari.utils.chunker import chunk, simple_chunk
from nokari.utils.converters import TimeConverter
from nokari.utils.formatter import discord_timestamp, escape_markdown, human_timedelta
from nokari.utils.paginator import Paginator
from nokari.utils.parser import ArgumentParser

MAX_DAYS: typing.Final[int] = 40
RETRY_IN: typing.Final[int] = 86400
_LOGGER = logging.getLogger("nokari.plugins.utils")


class SERIAL:
    ...


class ReminderTimerEvent(timers.BaseTimerEvent):
    ...


class Reminders(db.Table):
    id: db.PrimaryKeyColumn[SERIAL]
    expires_at: db.Column[datetime]
    created_at: db.Column[datetime]
    event: db.Column[str]
    extra: db.Column[dict]
    interval: db.Column[Snowflake]  # BIGINT


utils = Plugin("Utils", None, True)
utils.d.event = asyncio.Event()
REMIND_PARSER = (
    ArgumentParser()
    .interval("--interval", "-i", argmax=0, default=False)
    .daily("--daily", "-d", argmax=0, default=False)
)


async def get_active_timer() -> typing.Optional[timers.Timer]:
    query = "SELECT * FROM reminders WHERE expires_at < (CURRENT_TIMESTAMP + $1::interval) ORDER BY expires_at LIMIT 1;"
    record = await utils.bot.pool.fetchrow(query, timedelta(days=MAX_DAYS))
    return record and timers.Timer(record)


async def wait_for_active_timers() -> timers.Timer:
    timer = await utils.bot.get_active_timer()
    if timer is not None:
        utils.d.event.set()
        return timer

    utils.d.event.clear()
    utils.d_current_timer = None

    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(utils.d.event.wait(), timeout=RETRY_IN)

    return await wait_for_active_timers()


async def call_timer(timer: timers.Timer) -> None:
    args = [timer.id]

    _LOGGER.debug("Dispatching timer with interval %s", timer.interval)

    if timer.interval:
        query = "UPDATE reminders SET expires_at = CURRENT_TIMESTAMP + $2 * interval '1 sec' WHERE id=$1"
        args.append(timer.interval)
    else:
        query = "DELETE FROM reminders WHERE id=$1;"

    await utils.bot.pool.execute(query, *args)
    utils.bot.dispatch(timer.event(app=utils.bot, timer=timer))


async def dispatch_timers() -> None:
    try:
        while not utils.bot.is_alive:
            # dirty solution
            await asyncio.sleep(0.5)
        while utils.bot.is_alive:
            timer = utils.d._current_timer = await wait_for_active_timers()

            if timer.expires_at >= (now := datetime.now(timezone.utc)):
                await asyncio.sleep((timer.expires_at - now).total_seconds())

            await call_timer(timer)
    except (OSError, asyncpg.PostgresConnectionError):
        utils.d._task.cancel()
        utils.d._task = asyncio.create_task(dispatch_timers())


async def short_timer_optimisation(seconds: float, timer: timers.Timer) -> None:
    await asyncio.sleep(seconds)
    utils.bot.dispatch(timer.event(app=utils.bot, timer=timer))


async def create_timer(*args: typing.Any, **kwargs: typing.Any) -> timers.Timer:
    event, when, *args = args

    now = kwargs.pop("created_at", datetime.now(timezone.utc))
    interval = kwargs.pop("interval", 0)

    timer = timers.Timer.temporary(
        event=event,
        args=args,
        kwargs=kwargs,
        expires_at=when,
        created_at=now,
        interval=interval,
    )
    delta = (when - now).total_seconds()

    # Only optimise non-interval short timers
    if delta <= 60 and not interval:
        asyncio.create_task(short_timer_optimisation(delta, timer))
        return timer

    query = """INSERT INTO reminders (event, extra, expires_at, created_at, interval)
                VALUES ($1, $2::jsonb, $3, $4, $5)
                RETURNING id;
            """

    row = await utils.bot.pool.fetchrow(
        query, event, {"args": args, "kwargs": kwargs}, when, now, interval
    )
    timer.id = row[0]

    if delta <= (86400 * MAX_DAYS):
        utils.d.event.set()

    if utils.d._current_timer and when < utils.d._current_timer.expires_at:
        utils.d._task.cancel()
        utils.d._task = asyncio.create_task(dispatch_timers())

    return timer


async def verify_timer_integrity(id_: typing.Optional[int] = None) -> None:
    if id_ and (not utils.d._current_timer or utils.d._current_timer.id != id_):
        return

    utils.d._task.cancel()
    utils.d._task = asyncio.create_task(dispatch_timers())


@utils.command
@core.consume_rest_option("when", "The time for the bot to remind you.")
@core.command("remind", "Create a reminder.", signature="<when[, message]>")
@core.implements(lightbulb.commands.PrefixCommandGroup)
async def remind(ctx: Context) -> None:
    """
    You can pass a human readable time. The argument order doesn't really matter here,
    but you can't pass the time in between the reminder message. The time should be in UTC.

    Examples: - `n!remind me in a week do something`;
    - `n!remind me at 2pm do something`;
    - `n!remind do something 3h`;
    - `n!remind me in 4 hours do something -i`;
    - `n!remind --daily 4am do something.`.

    Flags:
    -i, --interval: continuously remind you at set interval;
    -d, --daily: same as interval with 24 hours period.
    """
    parsed = REMIND_PARSER.parse(None, ctx.options.when)
    dt, rem = await TimeConverter(ctx).convert(parsed.remainder)

    if parsed.interval and parsed.daily:
        raise ValueError("You can't specify both interval and daily flags.")

    interval = None

    if parsed.interval:
        if (temp := (dt - ctx.message.created_at).total_seconds()) < 300:
            raise ValueError("Interval can't be below 5 minutes.")

        interval = temp

    elif parsed.daily:
        interval = 86400

    rem = rem or "a."

    timer = await create_timer(
        "Reminder",
        dt,
        ctx.get_channel().id,
        ctx.author.id,
        rem,
        created_at=ctx.message.created_at,
        message_id=ctx.message.id,
        interval=interval,
    )
    reminder_id = f" Reminder ID: {timer.id}" if timer.id else ""
    fmt = "R"
    pre = ""

    if parsed.interval:
        reminder_id += f" with interval {human_timedelta(timedelta(seconds=typing.cast(float, interval)))}"
    elif parsed.daily:
        fmt = "t"
        pre = "at "
        reminder_id = f" Daily{reminder_id}"

    await ctx.respond(
        f"{ctx.author.mention},{reminder_id} {pre}"
        f"{discord_timestamp(timer.expires_at, fmt=fmt)}: {rem}"
        f"{'.'*(not rem.endswith('.'))}",
        user_mentions=[ctx.author],
    )


@remind.child
@core.command("list", "Shows your current active reminders.")
@core.implements(lightbulb.commands.PrefixSubCommand)
async def remind_list(ctx: Context) -> None:
    """
    Shows your current active remainders.
    """

    def get_embed(
        description: str,
        reminders: int,
        page: int,
        pages: int,
        syntax: str,
    ) -> hikari.Embed:
        zws = "\u200b"
        embed = hikari.Embed(
            title=f"{ctx.author}'s reminders:",
            description=f"```{syntax}\n{description.replace('`', zws+'`')}```",
            color=ctx.color,
        ).set_footer(
            text=f"{ctx.author} has {plural(reminders):reminder} | Page {page}/{pages}"
        )

        return embed

    async def get_page(pag: Paginator) -> typing.Tuple[hikari.Embed, int]:
        query = """SELECT id, expires_at, extra #>> '{args,2}'
                FROM reminders
                WHERE event = 'Reminder'
                AND extra #>> '{args,1}' = $1
                ORDER BY expires_at
                """
        records = await ctx.bot.pool.fetch(query, str(ctx.author.id))
        if not records:
            return get_embed("There is nothing here yet ._.", 0, 1, 1, "prolog"), 1

        table: typing.List[str] = sum(
            [
                list(
                    zip_longest(
                        *[
                            chunk(str(x), 16)
                            for x in (
                                _id,
                                textwrap.shorten(message, width=65, placeholder="..."),
                                human_timedelta(expires),
                            )
                        ],
                        fillvalue=None,
                    )
                )
                for _id, expires, message in records
            ],
            [],
        )
        headers = ["ID", "Message", "When"]
        chunked_table = simple_chunk(table, 20)
        max_ = len(chunked_table)
        pag.index = min(max_ - 1, pag.index)

        embed = get_embed(
            tabulate(chunked_table[pag.index], headers),
            len(records),
            pag.index + 1,
            max_,
            "ml",
        )

        return embed, max_

    await Paginator.default(ctx, callback=get_page).start()


@utils.listener
async def on_reminder(event: ReminderTimerEvent) -> None:
    channel_id, author_id, message = event.timer.args

    channel = (
        event.app.cache.get_guild_channel(channel_id)
        or event.app.cache.get_user(author_id)
        or await event.app.rest.fetch_user(author_id)
    )

    if (msg_id := event.timer.kwargs.get("message_id")) and (
        guild_id := getattr(channel, "guild_id", None)
    ):
        message += f'\n\n[Jump URL](https://discordapp.com/channels/{guild_id}/{channel.id}/{msg_id} "Jump to the message.")'

    embed = (
        hikari.Embed(
            title="Interval Timer" if event.timer.interval else "Reminder",
            color=event.app.default_color,
        )
        .add_field(name="ID:", value=str(event.timer.id))
        .add_field(
            name="Created on:",
            value=discord_timestamp(event.timer.created_at, fmt="F"),
        )
    )

    if event.timer.interval:
        embed.add_field(
            name="Interval:",
            value=human_timedelta(timedelta(seconds=event.timer.interval)),
        )

    embed.add_field(name="Message:", value=message)

    await channel.send(
        content=f"<@{author_id}>", embed=embed, user_mentions=[author_id]
    )


@utils.command
@core.command("reminders", "A convenient shortcut for the `remind list` command.")
@core.implements(lightbulb.commands.PrefixCommand)
async def _reminders(ctx: Context) -> None:
    """
    A convenient shortcut for the `remind list` command.
    """
    await remind_list.invoke(ctx)


@remind.child
@core.command("clear", "Clear all your active reminders.")
@core.implements(lightbulb.commands.PrefixSubCommand)
async def remind_clear(ctx: Context) -> None:
    """
    This will cancel all the reminders you've set up, note that there's no undo!
    """
    query = """SELECT id
                FROM reminders
                WHERE event = 'Reminder'
                AND extra #>> '{args,1}' = $1
            """

    author_id = str(ctx.author.id)
    records = await ctx.bot.pool.fetch(query, author_id)
    if not records:
        await ctx.respond("You haven't set any reminder, mate :flushed:")
        return None

    confirm = await ctx.bot.prompt(
        ctx,
        f"You're about to delete {plural(len(records)):reminder}",
        author_id=ctx.author.id,
        delete_after=False,
    )

    if not confirm:
        await ctx.respond("Aborted!")
        return None

    await verify_timer_integrity()

    query = (
        "DELETE FROM reminders WHERE event = 'Reminder' AND extra #>> '{args,1}' = $1"
    )
    await ctx.bot.pool.execute(query, author_id)
    await ctx.respond(f"Your {plural(len(records)):reminder} has been deleted.")


# pylint: disable=too-many-locals
@remind.child
@core.consume_rest_option("id", "The ID of the reminder to look up.")
@core.command("info", "View detailed info of a reminder", signature="<ID>")
@core.implements(lightbulb.commands.PrefixSubCommand)
async def remind_info(ctx: Context) -> None:
    """
    View detailed info of a reminder.

    The raw flag will escape the markdown, this is useful if you want to
    edit the message.

    Example: `n!remind info 378 --raw`

    Flags:
    -r, --raw: escape the markdown in the message.
    """
    parsed = (
        ArgumentParser()
        .raw("--raw", "-r", argmax=0, default=False)
        .parse(None, ctx.options.id)
    )

    if not parsed.remainder:
        await ctx.respond("Please specify the ID of the reminder.")
        return

    parsed.remainder = int(parsed.remainder)

    query = """SELECT created_at, expires_at, extra, interval
                FROM reminders
                WHERE event = 'Reminder'
                AND extra #>> '{args,1}' = $1
                AND id = $2
            """

    record = await ctx.bot.pool.fetchrow(query, str(ctx.author.id), parsed.remainder)
    if not record:
        await ctx.respond(f"You have no reminder with ID: {parsed.remainder}.")
        return

    interval = record["interval"]
    extra = record["extra"]
    channel_id, author_id, message = extra["args"]
    converter = escape_markdown if parsed.raw else lambda s: s
    embed = (
        hikari.Embed(title=f"Reminder no. {parsed.remainder}")
        .add_field(name="Message:", value=converter(message))
        .add_field(
            name="Created on:",
            value=discord_timestamp(record["created_at"], fmt="F"),
        )
    )

    if not interval:
        embed.add_field(
            name="Expires on:",
            value=discord_timestamp(record["expires_at"], fmt="F"),
        )

    embed.add_field(
        name=f"{'Next one' if interval else 'Expires'} in:",
        value=f"{human_timedelta(record['expires_at'])}",
    )

    if interval:
        embed.add_field(
            name="Interval:",
            value=human_timedelta(timedelta(seconds=interval)),
        )

    channel = (
        ctx.bot.cache.get_guild_channel(channel_id)
        or ctx.bot.cache.get_user(author_id)
        or await ctx.bot.rest.fetch_user(author_id)
    )

    has_guild = hasattr(channel, "guild_id")
    if (msg_id := extra["kwargs"].get("message_id")) and has_guild:
        embed.add_field(
            name="Jump URL",
            value=f'[Click here](https://discordapp.com/channels/{channel.guild_id}/{channel.id}/{msg_id} "Jump to the message.")',
        )

    await ctx.respond(embed=embed)


@remind.child
@core.greedy_option("ids", "The IDs of the reminder to delete", int)
@core.command(
    "delete",
    "Deletes your reminder(s)",
    signature="<ID...>",
    aliases=["cancel", "remove"],
)
async def remind_delete(ctx: Context) -> None:
    """
    This command can be greedy and take more than 1 ID.
    Example: `n!remind delete 243 244` with 243 and 244 as the IDs.
    """
    if not ctx.options.ids:
        await ctx.respond("Please specify the ID(s) of the reminder.")
        return

    author_id = str(ctx.author.id)
    deletes = []
    for identifier in ctx.options.ids:
        query = """DELETE FROM reminders
                    WHERE event = 'Reminder'
                    AND id = $1
                    AND extra #>> '{args,1}' = $2;
                """
        deleted = await ctx.bot.pool.execute(query, identifier, author_id)

        if deleted != "DELETE 0":
            await ctx.verify_timer_integrity(identifier)
            deletes.append(identifier)

    if not deletes:
        await ctx.respond(
            f"Are you sure you have "
            f"{'reminders with those IDs' if len(ctx.options.ids) > 1 else 'reminder with that ID'}?"
        )
        return

    plural_ = len(deletes) > 1
    reminder = "Reminders" if plural_ else "Reminder"
    have = "have" if plural_ else "has"

    await ctx.respond(
        f"{reminder} with ID {', '.join(map(str, deletes))} {have} been deleted."
    )


@remind.child
@core.consume_rest_option("message", "The new message.")
@core.option("id", "The ID of the reminder.", int)
@core.command(
    "edit", "Edit the message of your reminder.", signature="<ID> <new message>"
)
@core.implements(lightbulb.commands.PrefixSubCommand)
async def remind_edit(ctx: Context) -> None:
    """
    You can edit the message of the reminder in case you wanna add something.
    Note that it will replace the message instead of appending it.
    """
    query = """UPDATE reminders
                SET extra = jsonb_set(extra, '{args,2}', $1)
                WHERE id = $2
                AND extra #>> '{args,1}' = $3
            """
    updated = await ctx.bot.pool.execute(
        query, ctx.options.message, ctx.options.id, str(ctx.author.id)
    )

    if updated == "UPDATE 0":
        await ctx.respond("Hmm... there's no reminder with given ID.")
        return

    if utils.d._current_timer and utils.d._current_timer.id == ctx.options.id:
        utils.d._current_timer.args[2] = ctx.options.message  # type: ignore

    await ctx.respond(f"Alright, it's now set to {ctx.options.message}.")


def load(bot: BotApp) -> None:
    bot.add_plugin(utils, requires_db=True)
    if bot.pool:
        utils.d._task = asyncio.create_task(dispatch_timers())


def unload(bot: BotApp) -> None:
    bot.remove_plugin("Utils")
    with suppress(AttributeError):
        utils.d._task.cancel()  # TODO: remove_hook
