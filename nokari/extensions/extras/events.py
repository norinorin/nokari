from __future__ import annotations

from functools import partial
from typing import Any

from hikari import Embed
from hikari.colors import Color
from hikari.events.guild_events import GuildJoinEvent, GuildLeaveEvent
from hikari.events.message_events import GuildMessageCreateEvent
from hikari.guilds import GatewayGuild
from hikari.traits import RESTAware

from kita.command_handlers import GatewayCommandHandler
from kita.data import data
from kita.extensions import initializer, listener
from nokari import core
from nokari.core.bot import Nokari
from nokari.core.constants import GUILD_LOGS_WEBHOOK_URL
from nokari.utils import plural


async def handle_ping(event: GuildMessageCreateEvent) -> None:
    assert isinstance(event.app, core.Nokari)

    if not (me := event.app.get_me()) or event.message.content not in (
        f"<@{me.id}>",
        f"<@!{me.id}>",
    ):
        return

    await event.message.respond("Please use the slash commands instead.")


@listener()
async def on_message(event: GuildMessageCreateEvent) -> None:
    await handle_ping(event)


class WebhookExecutor:
    def __init__(self, app: RESTAware, webhook_url: str) -> None:
        webhook_id, webhook_token = GUILD_LOGS_WEBHOOK_URL.strip("/").split("/")[-2:]
        self.webhook_token = partial(
            app.rest.execute_webhook, int(webhook_id), webhook_token
        )

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.webhook_token(*args, **kwargs)


if GUILD_LOGS_WEBHOOK_URL:

    async def execute_guild_webhook(
        executor: WebhookExecutor,
        app: Nokari,
        guild: GatewayGuild | None,
        color: Color,
        suffix: str,
    ) -> None:
        embed = Embed(
            title=guild.name if guild else "Unknown guild",
            description=f"I'm now in {plural(len(app.cache.get_guilds_view())):server,}",
            color=color,
        )

        if guild:
            (
                embed.add_field(
                    "Owner:",
                    str(
                        guild.get_member(guild.owner_id)
                        or await app.rest.fetch_user(guild.owner_id)
                    ),
                )
                .add_field("Member count:", str(guild.member_count or 0))
                .add_field("ID:", str(guild.id))
            )

        await executor(embed=embed, username=f"{app.get_me()} {suffix}")

    @listener()
    async def on_guild_join(
        event: GuildJoinEvent, executor: WebhookExecutor = data(WebhookExecutor)
    ) -> None:
        await executor(event.guild, Color.of("#00FF00"), "(+)")

    @listener()
    async def on_guild_leave(
        event: GuildLeaveEvent, executor: WebhookExecutor = data(WebhookExecutor)
    ) -> None:
        # no clue why mypy complains that old_guild doesn't exist
        await executor(event.old_guild, Color.of("#FF0000"), "(-)")  # type: ignore


@initializer
def extension_initializer(handler: GatewayCommandHandler) -> None:
    if GUILD_LOGS_WEBHOOK_URL:
        handler.set_data(WebhookExecutor(handler.app, GUILD_LOGS_WEBHOOK_URL))
