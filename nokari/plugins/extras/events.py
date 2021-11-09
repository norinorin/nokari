from __future__ import annotations

import typing
from contextlib import suppress
from functools import partial

import hikari
from hikari import (
    Embed,
    GuildMessageCreateEvent,
    GuildMessageDeleteEvent,
    GuildMessageUpdateEvent,
    Message,
)
from hikari.colors import Color
from hikari.events.guild_events import GuildJoinEvent, GuildLeaveEvent
from hikari.guilds import GatewayGuild
from lightbulb import Bot, errors, plugins

from nokari.core.constants import GUILD_LOGS_WEBHOOK_URL, POSTGRESQL_DSN
from nokari.utils import plural

if not POSTGRESQL_DSN:
    from nokari.plugins.config import Config


class Events(plugins.Plugin):
    """
    A plugin that handles events.

    This plugin will process commands on message edits
    and delete the responses if the original messages were deleted.
    """

    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot

        if GUILD_LOGS_WEBHOOK_URL:
            webhook_id, webhook_token = GUILD_LOGS_WEBHOOK_URL.strip("/").split("/")[
                -2:
            ]
            self.execute_webhook = partial(
                self.bot.rest.execute_webhook, int(webhook_id), webhook_token
            )

            for event_type, callback in self.optional_events:
                bot.subscribe(event_type, callback)

    @property
    def optional_events(
        self,
    ) -> tuple[
        tuple[typing.Type[hikari.Event], typing.Callable[..., typing.Awaitable[None]]],
        ...,
    ]:
        return (
            (GuildJoinEvent, self.on_guild_join),
            (GuildLeaveEvent, self.on_guild_leave),
        )

    def plugin_remove(self) -> None:
        if GUILD_LOGS_WEBHOOK_URL:
            for event_type, callback in self.optional_events:
                self.bot.unsubscribe(event_type, callback)

    async def handle_ping(self, message: Message) -> None:

        if not (me := self.bot.get_me()) or message.content not in (
            f"<@{me.id}>",
            f"<@!{me.id}>",
        ):
            return

        ctx = self.bot.get_context(
            message,
            message.content,
            invoked_with="prefix",
            invoked_command=self.bot.get_command("prefix"),
        )

        if not self.bot.pool:
            embed = Embed(
                title="Prefixes",
                description=f"Default prefixes: {', '.join(Config.format_prefixes(self.bot.default_prefixes))}",
            )
            await ctx.respond(embed=embed)
            return

        with suppress(errors.CommandIsOnCooldown):
            return await self.bot.get_command("prefix").invoke(ctx)

    @plugins.listener()
    async def on_message(self, event: GuildMessageCreateEvent) -> None:
        await self.handle_ping(event.message)

    @plugins.listener()
    async def on_message_edit(self, event: GuildMessageUpdateEvent) -> None:
        if (
            event.is_bot is True
            or (message := self.bot.cache.get_message(event.message_id)) is None
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
        await self.bot.process_commands_for_event(message_create_event)
        await self.handle_ping(message)

    @plugins.listener()
    async def on_message_delete(self, event: GuildMessageDeleteEvent) -> None:
        if (
            resp := self.bot.cache.get_message(
                self.bot.responses_cache.pop(event.message_id, 0)
            )
        ) is None:
            return

        await resp.delete()

    async def execute_guild_webhook(
        self, guild: GatewayGuild | None, color: Color, suffix: str
    ) -> None:
        embed = Embed(
            title=guild.name if guild else "Unknown guild",
            description=f"I'm now in {plural(len(self.bot.cache.get_guilds_view())):server,}",
            color=color,
        )

        if guild:
            (
                embed.add_field(
                    "Owner:",
                    str(
                        guild.get_member(guild.owner_id)
                        or await self.bot.rest.fetch_user(guild.owner_id)
                    ),
                )
                .add_field("Member count:", str(guild.member_count or 0))
                .add_field("ID:", str(guild.id))
            )

        await self.execute_webhook(
            embed=embed, username=f"{self.bot.get_me()} {suffix}"
        )

    async def on_guild_join(self, event: GuildJoinEvent) -> None:
        await self.execute_guild_webhook(event.guild, Color.of("#00FF00"), "(+)")

    async def on_guild_leave(self, event: GuildLeaveEvent) -> None:
        await self.execute_guild_webhook(event.old_guild, Color.of("#FF0000"), "(-)")


def load(bot: Bot) -> None:
    bot.add_plugin(Events(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Events")
