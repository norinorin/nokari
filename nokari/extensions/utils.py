# Reminders based on RoboDanny.

import asyncio
import logging
import textwrap
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from typing import Any, AsyncIterator, Coroutine, Final, List, Optional, Tuple, cast

import hikari
from asyncpg import Pool
from asyncpg.exceptions import PostgresConnectionError
from hikari.commands import OptionType
from hikari.interactions.command_interactions import CommandInteraction
from hikari.messages import Message
from hikari.snowflakes import Snowflake
from tabulate import tabulate

from kita.command_handlers import GatewayCommandHandler
from kita.commands import command
from kita.contexts import Context
from kita.data import data
from kita.extensions import finalizer, initializer, listener
from kita.options import with_option
from kita.responses import Response, edit, respond
from nokari.core.bot import Nokari
from nokari.utils import db, plural, timers
from nokari.utils.chunker import chunk, simple_chunk
from nokari.utils.converters import parse_time
from nokari.utils.formatter import discord_timestamp, escape_markdown, human_timedelta
from nokari.utils.paginator import Paginator

MAX_DAYS: Final[int] = 40
RETRY_IN: Final[int] = 86400
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


class ReminderCore:
    def __init__(self, app: Nokari):
        self.app = app
        self.event = asyncio.Event()
        self.task = None
        self.current_timer = None

    @property
    def pool(self) -> Optional[Pool]:
        return self.app.pool

    def refresh_task(self) -> None:
        if self.task:
            self.task.cancel()

        self.task = asyncio.create_task(self.dispatch_timers())

    async def get_active_timer(self) -> Optional[timers.Timer]:
        query = "SELECT * FROM reminders WHERE expires_at < (CURRENT_TIMESTAMP + $1::interval) ORDER BY expires_at LIMIT 1;"
        record = await self.pool.fetchrow(query, timedelta(days=MAX_DAYS))
        return record and timers.Timer(record)

    async def wait_for_active_timers(self) -> timers.Timer:
        timer = await self.get_active_timer()
        if timer is not None:
            self.event.set()
            return timer

        self.event.clear()
        self.current_timer = None

        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.event.wait(), timeout=RETRY_IN)

        return await self.wait_for_active_timers()

    async def call_timer(self, timer: timers.Timer) -> None:
        args = [timer.id]

        _LOGGER.debug("Dispatching timer with interval %s", timer.interval)

        if timer.interval:
            query = "UPDATE reminders SET expires_at = CURRENT_TIMESTAMP + $2 * interval '1 sec' WHERE id=$1"
            args.append(timer.interval)
        else:
            query = "DELETE FROM reminders WHERE id=$1;"

        await self.pool.execute(query, *args)
        self.app.dispatch(timer.event(app=self.app, timer=timer))

    async def dispatch_timers(self) -> None:
        try:
            while not self.app.is_alive:
                # dirty solution
                await asyncio.sleep(0.5)
            while self.app.is_alive:
                timer = self.current_timer = await self.wait_for_active_timers()

                if timer.expires_at >= (now := datetime.now(timezone.utc)):
                    await asyncio.sleep((timer.expires_at - now).total_seconds())

                await self.call_timer(timer)
        except (OSError, PostgresConnectionError):
            self.refresh_task()

    async def short_timer_optimisation(
        self, seconds: float, timer: timers.Timer
    ) -> None:
        await asyncio.sleep(seconds)
        self.app.dispatch(timer.event(app=self.app, timer=timer))

    async def create_timer(self, *args: Any, **kwargs: Any) -> timers.Timer:
        event, when, *args = args

        now = kwargs.pop("created_at", datetime.now(timezone.utc))
        interval = kwargs.pop("interval", None)

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
            asyncio.create_task(self.short_timer_optimisation(delta, timer))
            return timer

        query = """INSERT INTO reminders (event, extra, expires_at, created_at, interval)
                    VALUES ($1, $2::jsonb, $3, $4, $5)
                    RETURNING id;
                """

        row = await self.app.pool.fetchrow(
            query, event, {"args": args, "kwargs": kwargs}, when, now, interval
        )
        timer.id = row[0]

        if delta <= (86400 * MAX_DAYS):
            self.event.set()

        if self.current_timer and when < self.current_timer.expires_at:
            self.refresh_task()

        return timer

    async def verify_timer_integrity(self, id_: Optional[int] = None) -> None:
        if id_ and (not self.current_timer or self.current_timer.id != id_):
            return

        self.refresh_task()


@command("reminder", "Reminder commands.")
def reminder() -> None:
    ...


@reminder.command("set", "Set a reminder.")
@with_option(OptionType.STRING, "when", "Human readable time offset.")
@with_option(OptionType.STRING, "thing", "Thing to remind.")
@with_option(OptionType.STRING, "interval", "The interval for continuous reminder.")
@with_option(OptionType.BOOLEAN, "daily", "Shortcut for 1 day interval.")
async def reminder_set(
    when: str,
    interval: Optional[str] = None,
    daily: bool = False,
    thing: str = "...",
    interaction: CommandInteraction = data(CommandInteraction),
    core: ReminderCore = data(ReminderCore),
) -> AsyncIterator[Response]:
    if interval and daily:
        yield respond("You can't specify both interval and daily flags.")
        return

    now = interaction.created_at

    interval_sec = None

    if interval:
        interval_sec = (parse_time(now, interval) - now).total_seconds()

    elif daily:
        interval_sec = 86400.0

    dt = parse_time(now, when)

    yield respond("Setting the timer...")

    message = await interaction.fetch_initial_response()

    timer = await core.create_timer(
        "Reminder",
        dt,
        interaction.channel_id,
        interaction.user.id,
        thing,
        created_at=now,
        message_id=message.id,
        interval=interval_sec,
    )
    reminder_id = f" Reminder ID: {timer.id}" if timer.id else ""
    fmt = "R"
    pre = ""

    if interval:
        reminder_id += f" with interval {human_timedelta(timedelta(seconds=cast(float, interval)))}"
    elif daily:
        fmt = "t"
        pre = "at "
        reminder_id = f" Daily{reminder_id}"

    yield edit(
        f"{interaction.user.mention},{reminder_id} {pre}"
        f"{discord_timestamp(timer.expires_at, fmt=fmt)}: {thing}"
        f"{'.'*(not thing.endswith('.'))}",  # why do I even care?
        user_mentions=[interaction.user],
    )


@reminder.command("list", "List your active reminders.")
def reminder_list(
    ctx: Context = data(Context), pool: Pool = data(Pool)
) -> Coroutine[Any, Any, Optional[Message]]:
    def get_embed(
        description: str,
        reminders: int,
        page: int,
        pages: int,
        syntax: str,
    ) -> hikari.Embed:
        zws = "\u200b"
        embed = hikari.Embed(
            title=f"{ctx.interaction.user}'s reminders:",
            description=f"```{syntax}\n{description.replace('`', zws+'`')}```",
            color=ctx.color,
        ).set_footer(
            text=f"{ctx.interaction.user} has {plural(reminders):reminder} | Page {page}/{pages}"
        )

        return embed

    async def get_page(pag: Paginator) -> Tuple[hikari.Embed, int]:
        query = """SELECT id, expires_at, extra #>> '{args,2}'
                FROM reminders
                WHERE event = 'Reminder'
                AND extra #>> '{args,1}' = $1
                ORDER BY expires_at
                """
        records = await pool.fetch(query, str(ctx.interaction.user.id))
        if not records:
            return get_embed("There is nothing here yet ._.", 0, 1, 1, "prolog"), 1

        table: List[str] = sum(
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

    return Paginator.default(ctx, callback=get_page).start()


@listener()
async def on_reminder(event: ReminderTimerEvent) -> None:
    assert isinstance(event.app, Nokari)
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


@command("reminders", "A convenient shortcut for the `remind list` command.")
def reminders(ctx: Context = data(Context)) -> Coroutine[Any, Any, Optional[Message]]:
    return reminder_list(ctx)


@reminder.command("clear", "Clear all your active reminders.")
async def reminder_clear(
    ctx: Context = data(Context),
    pool: Pool = data(Pool),
    core: ReminderCore = data(ReminderCore),
) -> None:
    query = """SELECT id
                FROM reminders
                WHERE event = 'Reminder'
                AND extra #>> '{args,1}' = $1
            """

    author_id = str(ctx.interaction.user.id)
    records = await pool.fetch(query, author_id)
    if not records:
        await ctx.respond("You haven't set any reminder, mate :flushed:")
        return None

    assert isinstance(ctx.app, Nokari)
    confirm = await ctx.app.prompt(
        ctx,
        f"You're about to delete {plural(len(records)):reminder}",
        author_id=ctx.interaction.user.id,
        delete_after=False,
    )

    if not confirm:
        await ctx.respond("Aborted!")
        return None

    await core.verify_timer_integrity()

    query = (
        "DELETE FROM reminders WHERE event = 'Reminder' AND extra #>> '{args,1}' = $1"
    )
    await pool.execute(query, author_id)
    await ctx.respond(f"Your {plural(len(records)):reminder} has been deleted.")


# pylint: disable=too-many-locals
@reminder.command("info", "View detailed info of your reminder.")
@with_option(OptionType.INTEGER, "id", "The ID of the reminder to look up.")
@with_option(OptionType.BOOLEAN, "raw", "Escape the markdown in the message.")
async def reminder_info(
    id: int, ctx: Context = data(Context), raw: bool = False, pool: Pool = data(Pool)
) -> None:
    query = """SELECT created_at, expires_at, extra, interval
                FROM reminders
                WHERE event = 'Reminder'
                AND extra #>> '{args,1}' = $1
                AND id = $2
            """

    record = await pool.fetchrow(query, str(ctx.interaction.user.id), id)
    if not record:
        await ctx.respond(f"You have no reminder with ID: {id}.")
        return

    interval = record["interval"]
    extra = record["extra"]
    channel_id, author_id, message = extra["args"]
    converter = escape_markdown if raw else lambda s: s
    embed = (
        hikari.Embed(title=f"Reminder no. {id}")
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
        ctx.app.cache.get_guild_channel(channel_id)
        or ctx.app.cache.get_user(author_id)
        or await ctx.app.rest.fetch_user(author_id)
    )

    has_guild = hasattr(channel, "guild_id")
    if (msg_id := extra["kwargs"].get("message_id")) and has_guild:
        embed.add_field(
            name="Jump URL",
            value=f'[Click here](https://discordapp.com/channels/{channel.guild_id}/{channel.id}/{msg_id} "Jump to the message.")',
        )

    await ctx.respond(embed=embed)


@reminder.command("delete", "Deletes your reminder(s")
@with_option(
    OptionType.STRING,
    "ids",
    "The ID(s) of the reminder to delete, separate with a space.",
)
async def reminder_delete(
    ids: str,
    ctx: Context = data(Context),
    pool: Pool = data(Pool),
    core: ReminderCore = data(ReminderCore),
) -> None:
    author_id = str(ctx.interaction.user.id)
    deletes = []
    cast_ids: List[int] = [int(id) for id in ids.split(" ")]
    for identifier in cast_ids:
        query = """DELETE FROM reminders
                    WHERE event = 'Reminder'
                    AND id = $1
                    AND extra #>> '{args,1}' = $2;
                """
        deleted = await pool.execute(query, identifier, author_id)

        if deleted != "DELETE 0":
            await core.verify_timer_integrity(identifier)
            deletes.append(identifier)

    if not deletes:
        await ctx.respond(
            f"Are you sure you have "
            f"{'reminders with those IDs' if len(cast_ids) > 1 else 'reminder with that ID'}?"
        )
        return

    plural_ = len(deletes) > 1
    reminder = "Reminders" if plural_ else "Reminder"
    have = "have" if plural_ else "has"

    await ctx.respond(
        f"{reminder} with ID {', '.join(map(str, deletes))} {have} been deleted."
    )


@initializer
def extension_initializer(handler: GatewayCommandHandler) -> None:
    assert isinstance(handler.app, Nokari)
    core = ReminderCore(handler.app)
    handler.set_data(core)
    handler.add_command(reminder)
    handler.subscribe(on_reminder)
    if not handler.get_data(Pool):
        raise RuntimeError("No pool was found")

    core.refresh_task()


@finalizer
def extension_finalizer(handler: GatewayCommandHandler) -> None:
    core = handler._data.pop(ReminderCore)
    handler.remove_command(reminder)
    handler.unsubscribe(on_reminder)
    if core.task:
        core.task.cancel()
        core.task = None
