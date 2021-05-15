"""A module that contains a custom command handler class implementation."""

import asyncio
import collections
import datetime
import logging
import os
import traceback
import typing
import weakref

import aiohttp
import hikari
import lightbulb
from lightbulb import checks, commands
from lightbulb.utils import maybe_await

from nokari.core.cache import Cache
from nokari.core.commands import command
from nokari.core.context import Context
from nokari.utils import human_timedelta

__all__: typing.Final[typing.List[str]] = ["Nokari"]
_KT = typing.TypeVar("_KT")
_VT = typing.TypeVar("_VT")


class FixedSizeDict(collections.MutableMapping[_KT, _VT], typing.Generic[_KT, _VT]):
    """A fixed size dict, mainly to cache responses the bot has made."""

    def __init__(
        self,
        length: int,
        *args: typing.Union[typing.Iterable[_VT], typing.Mapping[_KT, _VT]],
        **kwargs: typing.Any,
    ) -> None:
        self.length = length
        self._dict: typing.Dict[_KT, _VT] = dict(*args, **kwargs)
        while len(self) > length:
            self.popitem()

    def __iter__(self) -> typing.Iterator[typing.Any]:
        """Returns an iterator of the internal dict."""
        return iter(self._dict)

    def __len__(self) -> int:
        """Returns the length of the internal dict."""
        return len(self._dict)

    def __getitem__(self, _k: _KT) -> _VT:
        """Gets item from the internal dict."""
        return self._dict[_k]

    def __delitem__(self, _k: _KT) -> None:
        """Deletes item from the internal dict."""
        del self._dict[_k]

    def __setitem__(self, _k: _KT, _v: _VT) -> None:
        """Puts item to the internal dict."""
        if _k not in self and len(self) == self.length:
            self.popitem()
        self._dict[_k] = _v

    def __str__(self) -> str:
        """Returns the stringified internal dict."""
        return str(self._dict)

    def __repr__(self) -> str:
        """Returns the representation of the object."""
        return f"{self.__class__.__name__}(length={self.length}, **{self})"


class Nokari(lightbulb.Bot):
    """The custom command handler class."""

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
            prefix=["hikari", "test"],
            owner_ids=[265080794911866881],
        )

        # Custom cache
        self._cache = self._event_manager._cache = Cache(
            self, hikari.CacheSettings(invites=False, voice_states=False)
        )

        # Responses cache
        self._resp_cache: FixedSizeDict = FixedSizeDict(1024)

        # load extensions
        self.load_extensions()

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

    @property
    def default_color(self) -> hikari.Color:
        """Returns the dominant color of the bot's avatar"""
        return hikari.Color.from_rgb(251, 172, 37)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Returns an asyncio event loop."""
        return asyncio.get_event_loop()

    @property
    def session(self) -> typing.Optional[aiohttp.ClientSession]:
        """Returns a ClientSession"""
        return self._rest._client_session

    @property
    def responses_cache(self) -> FixedSizeDict[_KT, _VT]:
        """Returns a mapping from message ids to its response message ids."""
        return self._resp_cache

    @property
    def paginators(self) -> weakref.WeakValueDictionary:
        """Returns a mapping from message ids to active paginators."""
        return self._paginators

    async def on_started(self, _: hikari.StartedEvent) -> None:
        """Sets the launch time as soon as it connected to Discord gateway."""
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
    def raw_plugins(self) -> typing.List[str]:
        """Returns the Pythonic plugins path."""
        return [
            f"{path.strip('/').replace('/', '.')}.{file[:-3]}"
            for path, folders, files in os.walk("nokari/plugins/")
            for file in files
            if file.endswith(".py")
            and "__pycache__" not in path
            and "__init__" not in file
        ]

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
@command(name="reload")
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
