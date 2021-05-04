import asyncio
import collections
import datetime
import logging
import os
import sys
import traceback
import typing
import weakref

import hikari
import lightbulb
from lightbulb import checks, commands
from lightbulb.utils import maybe_await

from nokari.core.context import Context
from nokari.utils import human_timedelta

__all__: typing.Final[typing.List[str]] = ["Nokari"]
_KT = typing.TypeVar("_KT")
_VT = typing.TypeVar("_VT")


class FixedSizedDict(collections.MutableMapping[_KT, _VT], typing.Generic[_KT, _VT]):
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
        return iter(self._dict)

    def __len__(self) -> int:
        return len(self._dict)

    def __getitem__(self, k: _KT) -> _VT:
        return self._dict[k]

    def __delitem__(self, k: _KT) -> None:
        del self._dict[k]

    def __setitem__(self, k: _KT, v: _VT) -> None:
        if k not in self and len(self) == self.length:
            self.popitem()
        self._dict[k] = v

    def __str__(self) -> str:
        return str(self._dict)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(length={self.length}, **{self})"


class Nokari(lightbulb.Bot):
    def __init__(self) -> None:
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
            cache_settings=hikari.CacheSettings(invites=False, voice_states=False),
        )

        # Responses cache
        self._resp_cache: FixedSizedDict = FixedSizedDict(1024)

        # load extensions
        self.load_extensions()

        # Paginator caches
        self._paginators: weakref.WeakValueDictionary = weakref.WeakValueDictionary()

        # Subscribe to events
        self.event_manager.subscribe(hikari.StartedEvent, self.on_started)

        # Setup logger
        self.setup_logger()

        # Attach event loop
        self.loop = asyncio.get_event_loop()

        # Non-modular commands
        _ = [
            self.add_command(g)
            for g in globals().values()
            if isinstance(g, commands.Command)
        ]

    async def on_started(self, event: hikari.StartedEvent) -> None:
        """Sets the launch time as soon as it connected to Discord gateway"""
        self.launch_time = datetime.datetime.utcnow()

    def setup_logger(self) -> None:
        """Sets a logger that outputs to a file as well as stdout"""
        logging.basicConfig(filename="nokari.log", level=logging.INFO)
        self.log = logging.getLogger(self.__class__.__name__)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        self.log.addHandler(console)

    async def _resolve_prefix(self, message: hikari.Message) -> typing.Optional[str]:
        """Case-insensitive prefix resolver"""
        prefixes = await maybe_await(self.get_prefix, self, message)

        if isinstance(prefixes, str):
            prefixes = [prefixes]

        prefixes.sort(key=len, reverse=True)

        if message.content is not None:
            lowered_content = message.content.lower()
            content_length = len(lowered_content)
            for p in prefixes:
                if lowered_content.startswith(p):
                    while (p_length := len(p)) < content_length and (
                        next_char := lowered_content[p_length : p_length + 1]
                    ).isspace():
                        p += next_char
                        continue
                    return p
        return None

    def get_context(
        self,
        message: hikari.Message,
        prefix: str,
        invoked_with: str,
        invoked_command: commands.Command,
    ) -> Context:
        """Gets custom Context object"""
        return Context(self, message, prefix, invoked_with, invoked_command)

    @property
    def raw_plugins(self) -> typing.List[str]:
        """Returns the plugins path in Pythonic way"""
        dir_ = "nokari/plugins"
        return [
            f"{dir_.replace('/', '.')}.{ext[:-3]}"
            for ext in os.listdir(dir_)
            if ext.endswith(".py")
        ]

    @property
    def brief_uptime(self) -> str:
        """Returns formatted brief uptime"""
        return human_timedelta(self.launch_time, append_suffix=False, brief=True)

    def load_extensions(self) -> None:
        """Loads all the plugins"""
        for extension in self.raw_plugins:
            try:
                self.load_extension(extension)
            except lightbulb.errors.ExtensionMissingLoad:
                print(extension, "is missing load function.")
            except lightbulb.errors.ExtensionAlreadyLoaded:
                pass
            except lightbulb.errors.ExtensionError as e:
                print(extension, "failed to load.")
                print(
                    " ".join(
                        traceback.format_exception(
                            type(e or e.__cause__), e or e.__cause__, e.__traceback__
                        )
                    )
                )


@checks.owner_only()
@commands.command(name="reload")
async def reload_cog(ctx: Context, *, plugins: str = "*") -> None:
    await ctx.execute_plugins(ctx.bot.reload_extension, plugins)


@checks.owner_only()
@commands.command(name="unload")
async def unload_cog(ctx: Context, *, plugins: str = "*") -> None:
    await ctx.execute_plugins(ctx.bot.unload_extension, plugins)


@checks.owner_only()
@commands.command(name="load")
async def load_cog(ctx: Context, *, plugins: str = "*") -> None:
    await ctx.execute_plugins(ctx.bot.load_extension, plugins)
