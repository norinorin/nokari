"""A module that contains a custom command handler class implementation."""

import asyncio
import datetime
import functools
import importlib
import logging
import os
import sys
import traceback
import typing
import weakref

import aiohttp
import asyncpg
import hikari
import lightbulb
from hikari.snowflakes import Snowflake
from lightbulb import checks, commands
from lightbulb.utils import maybe_await
from lru import LRU  # pylint: disable=no-name-in-module

from nokari.core.cache import Cache
from nokari.core.commands import command, group
from nokari.core.context import Context
from nokari.core.entity_factory import EntityFactory
from nokari.utils import db, human_timedelta

__all__: typing.Final[typing.List[str]] = ["Nokari"]


def _get_prefixes(bot: lightbulb.Bot, message: hikari.Message) -> typing.List[str]:
    prefixes = bot.prefixes
    return prefixes.get(message.guild_id, bot.default_prefixes) + prefixes.get(
        message.author.id, []
    )


class Nokari(lightbulb.Bot):
    """The custom command handler class."""

    # pylint: disable=too-many-instance-attributes

    def __init__(self) -> None:
        """
        This doesn't take any arguments as we can
        manually put it when calling the superclass' __init__.
        """
        super().__init__(
            token=os.getenv("DISCORD_BOT_TOKEN"),
            banner="nokari.assets",
            intents=hikari.Intents.GUILDS
            | hikari.Intents.GUILD_EMOJIS
            | hikari.Intents.GUILD_MESSAGES
            | hikari.Intents.GUILD_MEMBERS
            | hikari.Intents.GUILD_MESSAGE_REACTIONS
            | hikari.Intents.GUILD_PRESENCES,
            insensitive_commands=True,
            prefix=lightbulb.when_mentioned_or(_get_prefixes),
            owner_ids=[265080794911866881],
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

        # Paginator caches
        self._paginators: weakref.WeakValueDictionary = weakref.WeakValueDictionary()

        # Subscribe to events
        self.event_manager.subscribe(hikari.StartedEvent, self.on_started)

        # Setup logger
        self.setup_logger()

        # Non-modular commands
        _ = [
            self.add_command(g)
            for g in globals().values()
            if isinstance(g, commands.Command)
        ]

        # Set Launch time
        self.launch_time: typing.Optional[datetime.datetime] = None

        # Default prefixes
        self.default_prefixes = ["nokari", "n!"]

    @functools.wraps(lightbulb.Bot.start)
    async def start(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        await super().start(*args, **kwargs)
        await self.create_pool()
        await self._load_prefixes()

    @functools.wraps(lightbulb.Bot.close)
    async def close(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        if self.pool:
            await self.pool.close()

        await super().close(*args, **kwargs)

    @property
    def default_color(self) -> hikari.Color:
        """Returns the dominant color of the bot's avatar."""
        return hikari.Color.from_rgb(251, 172, 37)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Returns the running event loop."""
        return asyncio.get_running_loop()

    @property
    def session(self) -> typing.Optional[aiohttp.ClientSession]:
        """Returns a ClientSession."""
        return self._rest._client_session

    @property
    def responses_cache(self) -> LRU:
        """Returns a mapping from message IDs to its response message IDs."""
        return self._resp_cache

    @property
    def paginators(self) -> weakref.WeakValueDictionary:
        """Returns a mapping from message IDs to active paginators."""
        return self._paginators

    @property
    def pool(self) -> typing.Optional[asyncpg.Pool]:
        return self._pool if hasattr(self, "_pool") else None

    async def create_pool(self) -> None:
        """Creates a connection pool."""
        self._pool = pool = await db.create_pool()

        if sys.argv[-1] == "init":
            await db.create_tables(pool)

    async def _load_prefixes(self) -> None:
        self.prefixes = {
            record["hash"]: record["prefixes"]
            for record in await self._pool.fetch("SELECT * FROM prefixes")
        }

    async def on_started(self, _: hikari.StartedEvent) -> None:
        """Sets the launch time as soon as it connected to Discord gateway."""
        # load extensions
        # Ensure every cogs are in async context.
        self.load_extensions()

        if self.launch_time is None:
            self.launch_time = datetime.datetime.utcnow()

    def setup_logger(self) -> None:
        """Sets a logger that outputs to a file as well as stdout."""
        self.log = logging.getLogger(self.__class__.__name__)

        file_handler = logging.handlers.TimedRotatingFileHandler(  # type: ignore
            "nokari.log", when="D", interval=7
        )
        file_handler.setLevel(logging.INFO)
        self.log.addHandler(file_handler)

    async def _resolve_prefix(self, message: hikari.Message) -> typing.Optional[str]:
        """Case-insensitive prefix resolver."""
        prefixes = await maybe_await(self.get_prefix, self, message)

        if isinstance(prefixes, str):
            prefixes = [prefixes]

        prefixes.sort(key=len, reverse=True)

        if message.content is not None:
            lowered_content = message.content.lower()
            content_length = len(lowered_content)
            for prefix in prefixes:
                prefix = prefix.strip()
                if lowered_content.startswith(prefix):
                    while (prefix_length := len(prefix)) < content_length and (
                        next_char := lowered_content[prefix_length : prefix_length + 1]
                    ).isspace():
                        prefix += next_char
                        continue
                    return prefix
        return None

    def get_context(
        self,
        message: hikari.Message,
        prefix: str,
        invoked_with: str,
        invoked_command: commands.Command,
    ) -> Context:
        """Gets custom Context object."""
        return Context(self, message, prefix, invoked_with, invoked_command)

    @property
    def raw_plugins(self) -> typing.Iterator[str]:
        """Returns the plugins' path component."""
        return (
            f"{path.strip('/').replace('/', '.')}.{file[:-3]}"
            for path, _, files in os.walk("nokari/plugins/")
            for file in files
            if file.endswith(".py")
            and "__pycache__" not in path
            and "__init__" not in file
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
        """Loads all the plugins."""
        for extension in self.raw_plugins:
            try:
                self.load_extension(extension)
            except lightbulb.errors.ExtensionMissingLoad:
                print(extension, "is missing load function.")
            except lightbulb.errors.ExtensionAlreadyLoaded:
                pass
            except lightbulb.errors.ExtensionError as _e:
                print(extension, "failed to load.")
                print(
                    " ".join(
                        traceback.format_exception(
                            type(_e or _e.__cause__),
                            _e or _e.__cause__,
                            _e.__traceback__,
                        )
                    )
                )


@checks.owner_only()
@group(name="reload")
async def reload_plugin(ctx: Context, *, plugins: str = "*") -> None:
    """Reloads certain or all the plugins."""
    await ctx.execute_plugins(ctx.bot.reload_extension, plugins)


@checks.owner_only()
@command(name="unload")
async def unload_plugin(ctx: Context, *, plugins: str = "*") -> None:
    """Unloads certain or all the plugins."""
    await ctx.execute_plugins(ctx.bot.unload_extension, plugins)


@checks.owner_only()
@command(name="load")
async def load_plugin(ctx: Context, *, plugins: str = "*") -> None:
    """Loads certain or all the plugins."""
    await ctx.execute_plugins(ctx.bot.load_extension, plugins)


@reload_plugin.command(name="module")
async def reload_module(ctx: Context, *, modules: str) -> None:
    """Hot-reload modules."""
    modules = set(modules.split())
    failed = set()
    parents = set()
    for mod in modules:
        parents.add(".".join(mod.split(".")[:-1]))
        try:
            module = sys.modules[mod]
            importlib.reload(module)
        except Exception as e:  # pylint: disable=broad-except
            ctx.bot.log.error("Failed to reload %s", mod, exc_info=e)
            failed.add((mod, e.__class__.__name__))

    for parent in parents:
        parent_split = parent.split(".")
        for idx in reversed(range(1, len(parent_split) + 1)):
            try:
                module = sys.modules[".".join(parent_split[:idx])]
                importlib.reload(module)
            except Exception as e:  # pylint: disable=broad-except
                ctx.bot.log.error("Failed to reload parent %s", parent, exc_info=e)

    loaded = "\n".join(f"+ {i}" for i in modules ^ {x[0] for x in failed})
    failed = "\n".join(f"- {m} {e}" for m, e in failed)
    await ctx.respond(f"```diff\n{loaded}\n{failed}```")
