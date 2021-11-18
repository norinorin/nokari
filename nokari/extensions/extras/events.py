from __future__ import annotations

from contextlib import suppress
from functools import partial

import lightbulb
from hikari import (
    Embed,
    GuildMessageCreateEvent,
    GuildMessageDeleteEvent,
    GuildMessageUpdateEvent,
)
from hikari.colors import Color
from hikari.events.guild_events import GuildJoinEvent, GuildLeaveEvent
from hikari.guilds import GatewayGuild
from lightbulb import errors

from nokari import core
from nokari.core.constants import GUILD_LOGS_WEBHOOK_URL, POSTGRESQL_DSN
from nokari.utils import plural

if not POSTGRESQL_DSN:
    from nokari.extensions.config import format_prefixes


events = core.Plugin("Events", None, True, hidden=True)


async def handle_ping(event: GuildMessageCreateEvent) -> None:
    assert isinstance(event.app, core.Nokari)

    if not (me := event.app.get_me()) or event.message.content not in (
        f"<@{me.id}>",
        f"<@!{me.id}>",
    ):
        return

    cmd = event.app.get_prefix_command("prefix")
    ctx = core.PrefixContext(event.app, event, cmd, "prefix", "")
    ctx._parser = lightbulb.utils.Parser(ctx, "")

    with suppress(errors.CommandIsOnCooldown):
        return await cmd.invoke(ctx)


@events.listener(GuildMessageCreateEvent)
async def on_message(event: GuildMessageCreateEvent) -> None:
    await handle_ping(event)


@events.listener(GuildMessageUpdateEvent)
async def on_message_edit(event: GuildMessageUpdateEvent) -> None:
    assert isinstance(event.app, core.Nokari)
    if (
        event.is_bot is True
        or (message := event.app.cache.get_message(event.message_id)) is None
        or event.old_message is None
    ):
        return

    # prevent embed from re-invoking commands
    if event.old_message.content == message.content:
        return

    message_create_event = (
        GuildMessageCreateEvent(  # pylint: disable=abstract-class-instantiated
            message=message, shard=event.shard
        )
    )
    await event.app.handle_messsage_create_for_prefix_commands(message_create_event)
    await handle_ping(message_create_event)


@events.listener(GuildMessageDeleteEvent)
async def on_message_delete(event: GuildMessageDeleteEvent) -> None:
    assert isinstance(event.app, core.Nokari)
    if (
        resp := event.app.cache.get_message(
            event.app.responses_cache.pop(event.message_id, 0)
        )
    ) is None:
        return

    await resp.delete()


async def execute_guild_webhook(
    guild: GatewayGuild | None, color: Color, suffix: str
) -> None:
    embed = Embed(
        title=guild.name if guild else "Unknown guild",
        description=f"I'm now in {plural(len(events.bot.cache.get_guilds_view())):server,}",
        color=color,
    )

    if guild:
        (
            embed.add_field(
                "Owner:",
                str(
                    guild.get_member(guild.owner_id)
                    or await events.bot.rest.fetch_user(guild.owner_id)
                ),
            )
            .add_field("Member count:", str(guild.member_count or 0))
            .add_field("ID:", str(guild.id))
        )

    await events.d.execute_webhook(
        embed=embed, username=f"{events.bot.get_me()} {suffix}"
    )


async def on_guild_join(event: GuildJoinEvent) -> None:
    await execute_guild_webhook(event.guild, Color.of("#00FF00"), "(+)")


async def on_guild_leave(event: GuildLeaveEvent) -> None:
    await execute_guild_webhook(event.old_guild, Color.of("#FF0000"), "(-)")


OPTIONAL_EVENTS = (
    (GuildJoinEvent, on_guild_join),
    (GuildLeaveEvent, on_guild_leave),
)


def load(bot: core.Nokari) -> None:
    bot.add_plugin(events)
    if GUILD_LOGS_WEBHOOK_URL:
        webhook_id, webhook_token = GUILD_LOGS_WEBHOOK_URL.strip("/").split("/")[-2:]
        events.d.execute_webhook = partial(
            bot.rest.execute_webhook, int(webhook_id), webhook_token
        )

        for event_type, callback in OPTIONAL_EVENTS:
            bot.subscribe(event_type, callback)


def unload(bot: core.Nokari) -> None:
    bot.remove_plugin("Events")
    if GUILD_LOGS_WEBHOOK_URL:
        # TODO: remove_hook
        for event_type, callback in OPTIONAL_EVENTS:
            bot.unsubscribe(event_type, callback)
