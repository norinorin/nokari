"""A module that contains a custom command handler class implementation."""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import shutil
import sys
import typing
import weakref
from contextlib import suppress

import aiohttp
import asyncpg
import hikari
import topgg
from hikari.commands import OptionType
from hikari.events.interaction_events import InteractionCreateEvent
from hikari.impl.bot import GatewayBot
from hikari.interactions.base_interactions import ResponseType
from hikari.interactions.component_interactions import ComponentInteraction
from hikari.messages import ButtonStyle
from hikari.snowflakes import Snowflake
from lru import LRU  # pylint: disable=no-name-in-module

from kita.checks import owner_only, with_check
from kita.command_handlers import GatewayCommandHandler
from kita.commands import command
from kita.data import data
from kita.errors import KitaError
from kita.options import with_option
from nokari.core import constants
from nokari.core.cache import Cache
from nokari.core.context import Context
from nokari.core.entity_factory import EntityFactory
from nokari.utils import db, human_timedelta

if typing.TYPE_CHECKING:
    from nokari.utils.paginator import Paginator

__all__ = ("Nokari",)
_LOGGER = logging.getLogger("nokari.core.bot")


class Messageable(typing.Protocol):
    respond: typing.Callable[..., typing.Coroutine[None, None, hikari.Message]]
    send: typing.Callable[..., typing.Coroutine[None, None, hikari.Message]]


class Nokari(GatewayBot):
    """The custom command handler class."""

    # pylint: disable=too-many-instance-attributes

    def __init__(self) -> None:
        """
        This doesn't take any arguments as we can
        manually put it when calling the superclass' __init__.
        """
        super().__init__(
            token=constants.DISCORD_BOT_TOKEN,
            banner="nokari.assets",
            intents=hikari.Intents.GUILDS
            | hikari.Intents.GUILD_EMOJIS
            | hikari.Intents.GUILD_MESSAGES
            | hikari.Intents.GUILD_MEMBERS
            | hikari.Intents.GUILD_MESSAGE_REACTIONS
            | hikari.Intents.GUILD_PRESENCES,
            logs=constants.LOG_LEVEL,
        )

        # Custom cache
        self._cache = self._event_manager._cache = Cache(
            self,
            hikari.CacheSettings(
                components=hikari.CacheComponents.ALL
                ^ (hikari.CacheComponents.VOICE_STATES | hikari.CacheComponents.INVITES)
            ),
        )

        # Custom entity factory
        self._entity_factory = self._rest._entity_factory = EntityFactory(self)

        # A mapping from user ids to their sync ids
        self._sync_ids: typing.Dict[Snowflake, str] = {}

        # Command handler
        self.handler = GatewayCommandHandler(
            self, constants.GUILD_IDS, context_type=Context
        )

        # Non-modular commands
        self.handler.add_command(extension)

        # Set Launch time
        self.launch_time: datetime.datetime | None = None

        # Default prefixes
        self.default_prefixes = ["nokari", "n!"]

        # Paginators
        self.paginators: typing.Mapping[
            Snowflake, Paginator
        ] = weakref.WeakValueDictionary()

        self.subscribe(hikari.StartingEvent, self.on_starting)
        self.subscribe(hikari.StartedEvent, self.on_started)
        self.subscribe(hikari.StoppingEvent, self.on_closing)

    async def _setup_topgg_clients(self) -> None:
        if constants.TOPGG_WEBHOOK_AUTH:
            self.webhook_manager = (
                topgg.WebhookManager()
                .endpoint()
                .type(topgg.WebhookType.BOT)
                .route("/dblwebhook")
                .auth(constants.TOPGG_WEBHOOK_AUTH)
                .callback(lambda data: _LOGGER.info("Receives vote %s", data))
                .add_to_manager()
            )

        if constants.TOPGG_TOKEN:
            me = self.get_me()
            assert me is not None
            self.dblclient = topgg.DBLClient(
                constants.TOPGG_TOKEN, default_bot_id=me.id
            )
            (
                self.dblclient.autopost()
                .on_success(lambda: _LOGGER.info("Successfully posted stats"))
                .stats(
                    lambda: topgg.StatsWrapper(
                        guild_count=len(self.cache.get_guilds_view()),
                        shard_count=self.shard_count,
                    )
                )
                .start()
            )

    async def _close_topgg_clients(self) -> None:
        if webhook_manager := getattr(self, "webhook_maanger", None):
            await webhook_manager.close()

        if dblclient := getattr(self, "dblclient", None):
            _LOGGER.info("Closing...")
            await dblclient.close()

    async def on_starting(self, _: hikari.StartingEvent) -> None:
        await self.create_pool()
        self.load_extensions()

    async def on_started(self, _: hikari.StartedEvent) -> None:
        self.launch_time = datetime.datetime.now(datetime.timezone.utc)

        if sys.argv[-1] == "init":
            await db.create_tables(self.pool)

        with suppress(FileNotFoundError):
            with open("tmp/restarting", "r", encoding="utf-8") as fp:
                raw = fp.read()

            shutil.rmtree("tmp", ignore_errors=True)
            if not raw:
                return

            await self.rest.edit_message(*raw.split("-"), "Successfully restarted!")

        await self._setup_topgg_clients()

    async def on_closing(self, _: hikari.StoppingEvent) -> None:
        if self.pool:
            await self.pool.close()
            delattr(self, "_pool")

        await self._close_topgg_clients()

    @property
    def default_color(self) -> hikari.Color:
        """Returns the dominant color of the bot's avatar."""
        return hikari.Color.from_rgb(251, 172, 37)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Returns the running event loop."""
        return asyncio.get_running_loop()

    @property
    def session(self) -> aiohttp.ClientSession | None:
        """Returns a ClientSession."""
        return self.rest._get_live_attributes().client_session

    @property
    def pool(self) -> asyncpg.Pool | None:
        return getattr(self, "_pool", None)

    async def create_pool(self) -> None:
        """Creates a connection pool."""
        if pool := await db.create_pool():
            self._pool = pool
            self.handler.set_data(pool)

    @property
    def raw_extensions(self) -> typing.Iterator[str]:
        """
        Returns the plugins' path component.

        I can actually do the following:
            return (
                f"{'.'.join(i.parts)}[:-3]"
                for i in Path("nokari/extensions").rglob("[!_]*.py")
            )

        Though, I found os.walk() is ~57%–70% faster (it shouldn't matter, but w/e.)
        """
        return (
            f"{path.strip('/').replace('/', '.')}.{file[:-3]}"
            for path, _, files in os.walk("nokari/extensions/")
            for file in files
            if file.endswith(".py")
            and "__pycache__" not in path
            and not file.startswith("_")
        )

    @property
    def brief_uptime(self) -> str:
        """Returns formatted brief uptime."""
        return (
            human_timedelta(self.launch_time, append_suffix=False, brief=True)
            if self.launch_time is not None
            else "Not available."
        )

    def load_extensions(self) -> None:
        """Loads all the extensions."""
        for extension in self.raw_extensions:
            try:
                self.handler.load_extension(extension)
            except Exception as _e:
                _LOGGER.error("%s failed to load", extension, exc_info=_e)

    # pylint: disable=lost-exception
    async def prompt(
        self,
        messageable: Messageable,
        message: str,
        *,
        author_id: int,
        timeout: float = 60.0,
        delete_after: bool = False,
    ) -> bool:
        color = self.default_color
        if isinstance(messageable, Context):
            color = messageable.color

        embed = hikari.Embed(description=message, color=color)
        component = (
            self.rest.build_action_row()
            .add_button(ButtonStyle.SUCCESS, "sure")
            .set_label("Sure")
            .add_to_container()
            .add_button(ButtonStyle.DANGER, "nvm")
            .set_label("Never mind")
            .add_to_container()
        )

        messageable = getattr(messageable, "channel", messageable)
        msg = await messageable.send(embed=embed, component=component)

        confirm = False

        def predicate(event: InteractionCreateEvent) -> bool:
            nonlocal confirm

            if not isinstance(event.interaction, ComponentInteraction):
                return False

            if (
                event.interaction.message.id != msg.id
                or event.interaction.user.id != author_id
            ):
                return False

            confirm = event.interaction.custom_id == "sure"
            return True

        try:
            event = await self.wait_for(
                InteractionCreateEvent, predicate=predicate, timeout=timeout
            )
        except asyncio.TimeoutError:
            pass

        try:
            if delete_after:
                await msg.delete()
            else:
                for c in component._components:
                    c._is_disabled = True

                await event.interaction.create_initial_response(
                    ResponseType.MESSAGE_UPDATE, component=component
                )
        finally:
            return confirm

    @property
    def me(self) -> hikari.OwnUser | None:
        """Temp fix until lightbub updates."""
        return self.get_me()


@command("extension", "Extension utilities.")
def extension() -> None:
    ...


@extension.command("reload", "Reloads extensions.")
@with_check(owner_only)
@with_option(OptionType.STRING, "extensions", "The extensions to reload.")
async def reload_plugin(ctx: Context = data(Context), extensions="*") -> None:
    await ctx.execute_extensions(ctx.handler.reload_extension, extensions)


@extension.command("unload", "Unloads extensions.")
@with_check(owner_only)
@with_option(OptionType.STRING, "extensions", "The extensions to unload.")
async def unload_plugin(ctx: Context = data(Context), extensions="*") -> None:
    await ctx.execute_extensions(ctx.handler.unload_extension, extensions)


@extension.command("load", "Loads extensions.")
@with_check(owner_only)
@with_option(OptionType.STRING, "extensions", "The extensions to load.")
async def load_plugin(ctx: Context = data(Context), extensions="*") -> None:
    await ctx.execute_extensions(ctx.handler.load_extension, extension)
