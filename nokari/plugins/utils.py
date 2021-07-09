# Reminders based on RoboDanny.

import asyncio
import textwrap
import typing
from datetime import datetime, timedelta, timezone
from itertools import zip_longest

import asyncpg
import hikari
from hikari.snowflakes import Snowflake
from lightbulb import Bot, Plugin, listener
from lightbulb.converters import Greedy, WrappedArg
from tabulate import tabulate

from nokari.core import command, group
from nokari.core.context import Context
from nokari.utils import db, plural, timers
from nokari.utils.chunker import chunk, simple_chunk
from nokari.utils.converters import time_converter
from nokari.utils.formatter import escape_markdown, human_timedelta
from nokari.utils.paginator import Paginator
from nokari.utils.parser import ArgumentParser


class SERIAL:
    ...


class Reminders(db.Table):
    id: db.PrimaryKeyColumn[SERIAL]
    expires_at: db.Column[datetime]
    created_at: db.Column[datetime]
    event: db.Column[str]
    extra: db.Column[dict]
    interval: db.Column[Snowflake]  # BIGINT


class Utils(Plugin):
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        super().__init__()

        self.event = asyncio.Event()
        self._current_timer: typing.Optional[timers.Timer] = None
        self._task: asyncio.Task[None] = asyncio.create_task(self.dispatch_timers())
        self._remind_parser = ArgumentParser().interval(
            "--interval", "-i", argmax=0, default=False
        )

    def plugin_remove(self) -> None:
        self._task.cancel()

    async def get_active_timer(self, *, days: int = 7) -> typing.Optional[timers.Timer]:
        query = "SELECT * FROM reminders WHERE expires_at < (CURRENT_DATE + $1::interval) ORDER BY expires_at LIMIT 1;"
        return (
            timers.Timer(record)
            if (record := await self.bot.pool.fetchrow(query, timedelta(days=days)))
            else None
        )

    async def wait_for_active_timers(self, *, days: int = 7) -> timers.Timer:
        timer = await self.get_active_timer(days=days)
        if timer is not None:
            self.event.set()
            return timer

        self.event.clear()
        self._current_timer = None
        try:
            await asyncio.wait_for(self.event.wait(), timeout=86400)
        except:
            return await self.wait_for_active_timers(days=days)
        else:
            return typing.cast(timers.Timer, await self.get_active_timer(days=days))

    async def call_timer(self, timer: timers.Timer) -> None:
        args = [timer.id]

        if timer.interval is None:
            query = "DELETE FROM reminders WHERE id=$1;"
        else:
            query = "UPDATE reminders SET expires_at = expires_at + $2 * interval '1 sec' WHERE id=$1"
            args.append(timer.interval)

        await self.bot.pool.execute(query, *args)
        self.bot.dispatch(timer.event(app=self.bot, timer=timer))

    async def dispatch_timers(self) -> None:
        try:
            while self.bot.is_alive:
                timer = self._current_timer = await self.wait_for_active_timers(days=40)

                if timer.expires_at >= (now := datetime.now(timezone.utc)):
                    await asyncio.sleep((timer.expires_at - now).total_seconds())

                await self.call_timer(timer)
        except (OSError, asyncpg.PostgresConnectionError):
            self._task.cancel()
            self._task = self.bot.loop.create_task(self.dispatch_timers())

    async def short_timer_optimisation(
        self, seconds: float, timer: timers.Timer
    ) -> None:
        await asyncio.sleep(seconds)
        self.bot.dispatch(timer.event(app=self.bot, timer=timer))

    async def create_timer(
        self, *args: typing.Any, **kwargs: typing.Any
    ) -> timers.Timer:
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
        if delta <= 60:
            asyncio.create_task(self.short_timer_optimisation(delta, timer))
            return timer

        query = """INSERT INTO reminders (event, extra, expires_at, created_at, interval)
                   VALUES ($1, $2::jsonb, $3, $4, $5)
                   RETURNING id;
                """

        row = await self.bot.pool.fetchrow(
            query, event, {"args": args, "kwargs": kwargs}, when, now, interval
        )
        timer.id = row[0]

        if delta <= (86400 * 40):
            self.event.set()

        if self._current_timer and when < self._current_timer.expires_at:
            self._task.cancel()
            self._task = self.bot.loop.create_task(self.dispatch_timers())

        return timer

    async def verify_timer_integrity(self, id_: typing.Optional[int] = None) -> None:
        if id_ and (not self._current_timer or self._current_timer.id != id_):
            return

        self._task.cancel()
        self._task = self.bot.loop.create_task(self.dispatch_timers())

    @group(
        usage="<when[, message]>",
        insensitive_commands=True,
    )
    async def remind(self, ctx: Context, *, when: str) -> None:
        """
        You can pass a human readable time. The argument order doesn't really matter here,
        but you can't pass the time in between the reminder message. The time should be in UTC.
        Examples: - `n!remind me in a week do something`
        - `n!remind me at 2pm do something`
        - `n!remind do something 3h`
        - `n!remind me in 4 hours do something`

        Flags:
        -i, --interval: continuously remind you at set interval.
        """
        parsed = self._remind_parser.parse(None, when)
        dt, rem = await time_converter(WrappedArg(parsed.remainder, ctx))

        if (
            interval := (dt - ctx.message.created_at).total_seconds()
        ) < 300 and parsed.interval:
            await ctx.respond("Interval can't be below 5 minutes.")
            return

        rem = rem or "a."

        timer = await self.create_timer(
            "reminder",
            dt,
            ctx.channel.id,
            ctx.author.id,
            rem,
            created_at=ctx.message.created_at,
            message_id=ctx.message.id,
            interval=parsed.interval and interval,
        )
        reminder_id = f" Reminder ID: {timer.id}" if timer.id else ""
        await ctx.respond(
            f"{ctx.author.mention}, {reminder_id} on <t:{int(timer.expires_at.timestamp())}:F>: {rem}"
        )

    @remind.command(name="list")
    async def remind_list(self, ctx: Context) -> None:
        """
        Shows your current active remainders...
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
                    WHERE event = 'reminder'
                    AND extra #>> '{args,1}' = $1
                    ORDER BY expires_at
                    """
            records = await self.bot.pool.fetch(query, str(ctx.author.id))
            if not records:
                return get_embed("There is nothing here yet ._.", 0, 1, 1, "prolog"), 1

            table = [
                a
                for i in [
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
                    for _id, expires, message in records
                ]
                for a in i
            ]
            headers = ["ID", "Message", "When"]
            chunked_table = simple_chunk(table, 20)
            max_ = len(chunked_table)

            embed = get_embed(
                tabulate(chunked_table[pag.index], headers),
                len(records),
                pag.index + 1,
                max_,
                "ml",
            )

            return embed, max_

        paginator = Paginator.default(ctx)
        paginator._callback = get_page
        await paginator.start()

    @listener()
    async def on_reminder(self, event: timers.ReminderTimerEvent) -> None:
        channel_id, author_id, message = event.timer.args

        channel = (
            self.bot.cache.get_guild_channel(channel_id)
            or self.bot.cache.get_user(author_id)
            or await self.bot.rest.fetch_user(author_id)
        )

        has_guild = hasattr(channel, "guild_id")
        if (msg_id := event.timer.kwargs.get("message_id")) and has_guild:
            message += f'\n\n[Jump URL](https://discordapp.com/channels/{channel.guild_id}/{channel.id}/{msg_id} "Jump to the message")'

        embed = (
            hikari.Embed(
                title="Interval Timer"
                if event.timer.interval is not None
                else "Reminder",
                color=self.bot.default_color,
            )
            .add_field(name="ID:", value=str(event.timer.id))
            .add_field(
                name="Created on:",
                value=f"<t:{int(event.timer.created_at.timestamp())}:F>",
            )
        )

        if event.timer.interval is not None:
            embed.add_field(
                name="Interval:",
                value=human_timedelta(
                    datetime.now(timezone.utc) + timedelta(seconds=event.timer.interval)
                ),
            )

        embed.add_field(name="Message:", value=message)

        await channel.send(content=f"<@{author_id}>", embed=embed)

    @command(name="reminders", hidden=True)
    async def reminders(self, ctx: Context) -> None:
        await self.remind_list.invoke(ctx)

    @remind.command(name="clear", allow_extra_arguments=False)
    async def remind_clear(self, ctx: Context) -> None:
        """
        This will cancel all the reminders you've set up, note that there's no undo!
        """
        query = """SELECT id
                   FROM reminders
                   WHERE event = 'reminder'
                   AND extra #>> '{args,1}' = $1
                """

        author_id = str(ctx.author.id)
        records = await self.bot.pool.fetch(query, author_id)
        if not records:
            await ctx.respond("You haven't set any reminder, mate :flushed:")
            return None

        confirm = await self.bot.prompt(
            ctx,
            f"You're about to delete {plural(len(records)):reminder}",
            author_id=ctx.author.id,
        )
        if not confirm:
            await ctx.respond("Aborted!")
            return None

        await self.verify_timer_integrity()

        query = "DELETE FROM reminders WHERE event = 'reminder' AND extra #>> '{args,1}' = $1"
        await self.bot.pool.execute(query, author_id)
        await ctx.respond(f"Your {plural(len(records)):reminder} has been deleted")

    @remind.command(name="info", usage="<ID>")
    async def remind_info(self, ctx: Context, *, id_: str) -> None:
        """
        View detailed info of a reminder.

        The raw flag will escape the markdown, this is useful if you want to
        edit the message.
        Example: `n!remind info 378 --raw`

        Flags:
        -r, --raw: escape the markdown in the message
        """
        parsed = (
            ArgumentParser()
            .raw("--raw", "-r", argmax=0, default=False)
            .parse(None, id_)
        )

        if not parsed.remainder:
            await ctx.send("Please specify the ID of the reminder.")
            return

        parsed.remainder = int(parsed.remainder)

        query = """SELECT created_at, expires_at, extra, interval
                   FROM reminders
                   WHERE event = 'reminder'
                   AND extra #>> '{args,1}' = $1
                   AND id = $2
                """

        def format_dt(dt: datetime) -> str:
            return f"<t:{int(dt.timestamp())}:F>"

        record = await self.bot.pool.fetchrow(
            query, str(ctx.author.id), parsed.remainder
        )
        if not record:
            await ctx.send(f"You have no reminder with ID: {parsed.remainder}.")

        extra = record["extra"]
        channel_id, author_id, message = extra["args"]
        converter = escape_markdown if parsed.raw else lambda s: s
        embed = (
            hikari.Embed(title=f"Reminder no. {parsed.remainder}")
            .add_field(name="Message:", value=converter(message))
            .add_field(name="Created on:", value=format_dt(record["created_at"]))
            .add_field(name="Expires on:", value=format_dt(record["expires_at"]))
            .add_field(name="Expires in:", value=human_timedelta(record["expires_at"]))
        )

        if record["interval"] is not None:
            embed.add_field(
                name="Interval:",
                value=human_timedelta(
                    datetime.now(timezone.utc) + timedelta(seconds=record["interval"])
                ),
            )

        channel = (
            self.bot.cache.get_guild_channel(channel_id)
            or self.bot.cache.get_user(author_id)
            or await self.bot.rest.fetch_user(author_id)
        )

        has_guild = hasattr(channel, "guild_id")
        if (msg_id := extra["kwargs"].get("message_id")) and has_guild:
            embed.add_field(
                name="Jump URL",
                value=f'[Click here](https://discordapp.com/channels/{channel.guild_id}/{channel.id}/{msg_id} "Jump to the message")',
            )

        await ctx.respond(embed=embed)

    @remind.command(
        name="delete",
        aliases=["cancel", "remove"],
        usage="<ID...>",
        allow_extra_arguments=False,
    )
    async def remind_delete(self, ctx: Context, ids: Greedy[int] = None) -> None:
        """
        This command can be greedy and take more than 1 ID.
        Example: `n!remind delete 243 244` with 243 and 244 as the IDs
        """
        if not ids:
            await ctx.respond("Please specify the ID(s) of the reminder")
            return

        author_id = str(ctx.author.id)
        deletes = []
        for identifier in ids:
            query = """DELETE FROM reminders
                       WHERE event = 'reminder'
                       AND id = $1
                       AND extra #>> '{args,1}' = $2;
                    """
            deleted = await self.bot.pool.execute(query, identifier, author_id)

            if deleted != "DELETE 0":
                await self.verify_timer_integrity(identifier)
                deletes.append(identifier)

        plural = "reminders with those IDs" if len(ids) > 1 else "reminder with that ID"
        if not deletes:
            await ctx.respond(f"Are you sure you have {plural}?")
            return

        plural = len(deletes) > 1
        reminder = "Reminders" if plural else "Reminder"
        have = "have" if plural else "has"

        await ctx.respond(
            f"{reminder} with id {', '.join(map(str, deletes))} {have} been deleted"
        )

    @remind.command(
        name="edit",
        usage="<ID> <new message>",
        allow_extra_arguments=False,
    )
    async def remind_edit(self, ctx: Context, id_: int, *, message: str) -> None:
        """
        You can edit the message of the reminder in case you wanna add something.
        Note that it will replace the message instead of appending it.
        """
        query = """UPDATE reminders
                   SET extra = jsonb_set(extra, '{args,2}', $1)
                   WHERE id = $2
                   AND extra #>> '{args,1}' = $3
                """
        updated = await self.bot.pool.execute(query, message, id_, str(ctx.author.id))

        if updated == "UPDATE 0":
            await ctx.respond("Hmm... there's no reminder with given ID.")
            return

        if self._current_timer and self._current_timer.id == id_:
            self._current_timer.args[2] = message  # type: ignore

        await ctx.respond(f"Alright, it's now set to {message}")


def load(bot: Bot) -> None:
    bot.add_plugin(Utils(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Utils")
