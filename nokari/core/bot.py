"""A module that contains a custom command handler class implementation."""
from __future__ import annotations

import asyncio
import datetime
import importlib
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
import lightbulb
import topgg
from hikari.events.interaction_events import InteractionCreateEvent
from hikari.interactions.base_interactions import ResponseType
from hikari.interactions.component_interactions import ComponentInteraction
from hikari.messages import ButtonStyle
from hikari.snowflakes import Snowflake
from lightbulb import checks
from lru import LRU  # pylint: disable=no-name-in-module

from nokari.core import commands, constants
from nokari.core.cache import Cache
from nokari.core.context import PrefixContext
from nokari.core.entity_factory import EntityFactory
from nokari.utils import db, human_timedelta

if typing.TYPE_CHECKING:
    from nokari.utils.paginator import Paginator

__all__: typing.Final[typing.List[str]] = ["Nokari"]
_LOGGER = logging.getLogger("nokari.core.bot")


def _get_prefixes(bot: lightbulb.Bot, message: hikari.Message) -> typing.List[str]:
    if not hasattr(bot, "prefixes"):
        return bot.default_prefixes

    prefixes = bot.prefixes
    return prefixes.get(message.guild_id, bot.default_prefixes) + prefixes.get(
        message.author.id, []
    )


class Messageable(typing.Protocol):
    respond: typing.Callable[..., typing.Coroutine[None, None, hikari.Message]]
    send: typing.Callable[..., typing.Coroutine[None, None, hikari.Message]]


class Nokari(lightbulb.BotApp):
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
            case_insensitive_prefix_commands=True,
            prefix=lightbulb.when_mentioned_or(_get_prefixes),
            owner_ids=[265080794911866881],
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

        # Responses cache
        self._resp_cache = LRU(1024)

        # Non-modular commands
        _ = [
            self.command(g)
            for g in globals().values()
            if isinstance(g, lightbulb.commands.CommandLike)
        ]

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
        self._load_extensions()

    async def on_started(self, _: hikari.StartedEvent) -> None:
        self.launch_time = datetime.datetime.now(datetime.timezone.utc)

        if sys.argv[-1] == "init":
            await db.create_tables(self.pool)

        await self._load_prefixes()

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
    def responses_cache(self) -> LRU:
        """Returns a mapping from message IDs to its response message IDs."""
        return self._resp_cache

    @property
    def pool(self) -> asyncpg.Pool | None:
        return getattr(self, "_pool", None)

    async def create_pool(self) -> None:
        """Creates a connection pool."""
        if pool := await db.create_pool():
            self._pool = pool

    async def _load_prefixes(self) -> None:
        if self.pool:
            self.prefixes = {
                record["hash"]: record["prefixes"]
                for record in await self.pool.fetch("SELECT * FROM prefixes")
            }

    def get_prefix_context(
        self,
        event: hikari.MessageCreateEvent,
        cls: typing.Type[lightbulb.context.prefix.PrefixContext] = PrefixContext,
    ) -> typing.Awaitable[typing.Optional[lightbulb.context.prefix.PrefixContext]]:
        return super().get_prefix_context(event, cls=cls)

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

    def _load_extensions(self) -> None:
        """Loads all the plugins."""
        for extension in self.raw_extensions:
            try:
                self.load_extensions(extension)
            except lightbulb.errors.ExtensionMissingLoad:
                _LOGGER.error("%s is missing load function", extension)
            except lightbulb.errors.ExtensionAlreadyLoaded:
                pass
            except lightbulb.errors.LightbulbError as _e:
                _LOGGER.error("%s failed to load", exc_info=_e)

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
        if isinstance(messageable, PrefixContext):
            color = messageable.color
        else:
            color = self.default_color

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

    def add_plugin(
        self,
        plugin: lightbulb.Plugin | typing.Type[lightbulb.Plugin],
        requires_db: bool = False,
    ) -> None:
        if requires_db and self.pool is None:
            if (name := getattr(plugin, "name", None)) is None:
                name = plugin.__class__.name  # type: ignore

            _LOGGER.warning("Not loading %s plugin as it requires DB", name)
            return None

        return super().add_plugin(plugin)


@commands.add_checks(checks.owner_only)
@commands.consume_rest_option("plugins", "The plugins to reload.", default="*")
@commands.command("reload", "Reloads plugins.")
@commands.implements(lightbulb.commands.PrefixCommandGroup)
async def reload_plugin(ctx: PrefixContext) -> None:
    await ctx.execute_extensions(ctx.bot.reload_extensions, ctx.options.plugins)


@lightbulb.add_checks(checks.owner_only)
@commands.consume_rest_option("plugins", "The plugins to unload.", default="*")
@commands.command("unload", "Unloads plugins.")
@commands.implements(lightbulb.commands.PrefixCommandGroup)
async def unload_plugin(ctx: PrefixContext) -> None:
    await ctx.execute_extensions(ctx.bot.unload_extensions, ctx.options.plugins)


@lightbulb.add_checks(checks.owner_only)
@commands.consume_rest_option("plugins", "The plugins to load.", default="*")
@commands.command("load", "Loads plugins.")
@commands.implements(lightbulb.commands.PrefixCommandGroup)
async def load_plugin(ctx: PrefixContext) -> None:
    await ctx.execute_extensions(ctx.bot.load_extensions, ctx.options.plugins)


@reload_plugin.child
@lightbulb.add_checks(checks.owner_only)
@commands.consume_rest_option("modules", "Modules to reload.")
@commands.command("module", "Reloads modules.")
@commands.implements(lightbulb.commands.PrefixSubCommand)
async def reload_module(ctx: PrefixContext) -> None:
    """Hot-reload modules."""
    modules = set(ctx.options.modules.split())
    failed = set()
    parents = set()
    for mod in modules:
        parents.add(".".join(mod.split(".")[:-1]))
        try:
            module = sys.modules[mod]
            importlib.reload(module)
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.error("Failed to reload %s", mod, exc_info=e)
            failed.add((mod, e.__class__.__name__))

    for parent in parents:
        parent_split = parent.split(".")
        for idx in reversed(range(1, len(parent_split) + 1)):
            try:
                module = sys.modules[".".join(parent_split[:idx])]
                importlib.reload(module)
            except Exception as e:  # pylint: disable=broad-except
                _LOGGER.error("Failed to reload parent %s", parent, exc_info=e)

    loaded = "\n".join(f"+ {i}" for i in modules ^ {x[0] for x in failed})
    failed = "\n".join(f"- {m} {e}" for m, e in failed)
    await ctx.respond(f"```diff\n{loaded}\n{failed}```")
