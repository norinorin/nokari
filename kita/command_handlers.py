from __future__ import annotations

import asyncio
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    MutableMapping,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
    cast,
)
from weakref import WeakValueDictionary

from hikari.api.special_endpoints import CommandBuilder
from hikari.events.interaction_events import InteractionCreateEvent
from hikari.events.lifetime_events import StartedEvent
from hikari.impl.bot import GatewayBot
from hikari.interactions.base_interactions import InteractionType
from hikari.interactions.command_interactions import CommandInteraction
from hikari.snowflakes import Snowflakeish
from hikari.undefined import UNDEFINED, UndefinedOr

from kita.buckets import EmptyBucketError
from kita.commands import command
from kita.contexts import Context
from kita.data import DataContainerMixin
from kita.errors import (
    CheckError,
    CommandNameConflictError,
    CommandOnCooldownError,
    CommandRuntimeError,
    ExtensionFinalizationError,
    ExtensionInitializationError,
    KitaError,
    MissingCommandCallbackError,
)
from kita.events import CommandCallEvent, CommandFailureEvent, CommandSuccessEvent
from kita.extensions import (
    listener,
    load_components,
    load_extension,
    reload_extension,
    unload_components,
    unload_extension,
)
from kita.typedefs import (
    CallableProto,
    CommandCallback,
    CommandContainer,
    EventCallback,
    Extension,
    ICommandCallback,
    IGroupCommandCallback,
)
from kita.utils import get_command_builder

if TYPE_CHECKING:
    from hikari.api.event_manager import CallbackT, EventT, EventT_co

__all__ = ("GatewayCommandHandler",)
_LOGGER = logging.getLogger("kita.command_handler")


class GatewayCommandHandler(DataContainerMixin):
    __slots__ = (
        "app",
        "guild_ids",
        "owner_ids",
        "context_type",
        "_commands",
        "_extensions",
        "_listeners",
    )

    def __init__(
        self,
        app: GatewayBot,
        guild_ids: Optional[Set[Snowflakeish]] = None,
        owner_ids: Optional[Set[Snowflakeish]] = None,
        context_type: Type[Context] = Context,
    ) -> None:
        super().__init__()
        self.app = app
        self.set_data(app)
        self._commands: CommandContainer = {}
        self._extensions: Dict[str, Extension] = {}
        self.guild_ids = guild_ids or set()
        self.owner_ids = owner_ids or set()
        self._listeners: MutableMapping[
            EventCallback, CallbackT
        ] = WeakValueDictionary()
        self.context_type = context_type
        app.subscribe(StartedEvent, self._on_started)
        app.subscribe(InteractionCreateEvent, self._process_command_interaction)

    def _wrap_event_callback(self, func: EventCallback[EventT]) -> CallbackT[EventT]:
        async def callback(event: EventT) -> Any:
            return await self._invoke_callback(func, event)

        self._listeners[func] = callback
        return callback

    def listen(
        self, event_type: Optional[Type[EventT_co]] = None
    ) -> Callable[[CallbackT[EventT_co]], CallbackT[EventT_co]]:
        def decorator(func: CallbackT[EventT_co]) -> CallbackT[EventT_co]:
            return self.app.listen(event_type)(
                self._wrap_event_callback(listener(event_type)(func))
            )

        return decorator

    def subscribe(
        self,
        callback: EventCallback[EventT_co],
    ) -> None:
        self.app.subscribe(callback.__etype__, self._wrap_event_callback(callback))

    def unsubscribe(self, callback: EventCallback[EventT_co]) -> None:
        self.app.unsubscribe(callback.__etype__, self._listeners.pop(callback))

    @property
    def commands(self) -> CommandContainer:
        return self._commands

    def command(
        self,
        name: str,
        description: str,
        guild_ids: UndefinedOr[Set[Snowflakeish]] = UNDEFINED,
    ) -> Callable[[CallableProto], CommandCallback]:
        def decorator(func: CallableProto) -> CommandCallback:
            self.add_command(func := command(name, description, guild_ids)(func))
            return func

        return decorator

    def add_command(self, func: CommandCallback, /) -> None:
        if func.__name__ in self._commands:
            raise CommandNameConflictError(
                f"command {func.__name__!r} already has a callback."
            )

        self._commands[func.__name__] = func

    def remove_command(self, func_or_name: Union[CommandCallback, str]) -> None:
        if not isinstance(func_or_name, str):
            func_or_name = func_or_name.__name__

        del self._commands[func_or_name]

    def get_command(self, name: str) -> Optional[ICommandCallback]:
        ret: Optional[ICommandCallback]
        names = name.split()
        if not (ret := self.commands.get(names.pop(0))):
            return None

        while names:
            if not (
                ret := cast(
                    MutableMapping[str, ICommandCallback],
                    getattr(ret, "__sub_commands__", {}),
                ).get(names.pop(0))
            ):
                return None

        return ret

    def _load_module(self, mod: Extension) -> None:
        name = mod.__name__
        try:
            mod.__einit__ and mod.__einit__(self)
        except Exception as e:
            unload_extension(name)
            raise ExtensionInitializationError(e, mod) from e
        else:
            self._extensions[name] = mod
            load_components(self, mod)

    def _unload_module(self, mod: Extension) -> None:
        name = mod.__name__
        try:
            mod.__edel__ and mod.__edel__(self)
        except Exception as e:
            load_extension(name)
            raise ExtensionFinalizationError(e, mod) from e
        else:
            del self._extensions[name]
            unload_components(self, mod)

    def load_extension(self, name: str) -> None:
        mod = load_extension(name)
        self._load_module(mod)

    def unload_extension(self, name: str) -> None:
        mod = unload_extension(name)
        self._unload_module(mod)

    def reload_extension(self, name: str) -> None:
        old, new = reload_extension(name)
        self._unload_module(old)
        self._load_module(new)

    async def _on_started(self, _: StartedEvent) -> None:
        app = await self.app.rest.fetch_application()
        self.owner_ids.add(app.owner.id)

        if app.team:
            self.owner_ids |= set(app.team.members.keys())

        await self._sync()

    async def _sync(self) -> None:
        commands: List[CommandBuilder] = []
        guild_commands: MutableMapping[Snowflakeish, List[CommandBuilder]] = {}
        for callback in self._commands.values():
            builder = get_command_builder(callback)
            if guild_ids := callback.__guild_ids__ | self.guild_ids:
                for guild_id in guild_ids:
                    guild_commands.setdefault(guild_id, []).append(builder)
            else:
                commands.append(builder)

        app = self.app.get_me()
        assert app is not None

        await self.app.rest.set_application_commands(app.id, commands)

        for guild_id, commands in guild_commands.items():
            await self.app.rest.set_application_commands(app.id, commands, guild_id)

    def _resolve_cb(
        self, interaction: CommandInteraction
    ) -> Tuple[ICommandCallback, Dict[str, Any]]:
        options = interaction.options
        cb: ICommandCallback = self._commands[interaction.command_name]

        while options and (option := options[0]).type in (1, 2):
            cb = cast(IGroupCommandCallback, cb).__sub_commands__[option.name]
            options = option.options

        return cb, {o.name: o.value for o in options or []}

    async def _process_command_interaction(self, event: InteractionCreateEvent) -> None:

        if (
            interaction := event.interaction
        ).type is not InteractionType.APPLICATION_COMMAND:
            return

        assert isinstance(interaction, CommandInteraction)

        ctx = self.context_type(event, self)

        try:
            cb, options = self._resolve_cb(interaction)
        except KeyError:
            await self._dispatch_command_failure(
                ctx,
                MissingCommandCallbackError(
                    f"couldn't find any implementation for {interaction.command_name!r}"
                ),
            )
            return

        ctx.set_command(cb)

        if bucket_manager := cb.__bucket_manager__:
            try:
                bucket_manager.get_bucket(event).acquire()
            except EmptyBucketError as exc:
                await self._dispatch_command_failure(
                    ctx,
                    CommandOnCooldownError(
                        f"you're in cooldown, please try again in {exc.retry_after} seconds.",
                        retry_after=exc.retry_after,
                    ),
                )
                return

        await self.app.dispatch(CommandCallEvent(self.app, ctx))

        extra_env: MutableMapping[Type[Any], Any] = {
            InteractionCreateEvent: event,
            CommandInteraction: event.interaction,
            self.context_type: ctx,
        }

        try:
            if not all(
                await asyncio.gather(
                    *[
                        self._invoke_callback(check, extra_env=extra_env)
                        for check in cb.__checks__
                    ]
                )
            ):
                raise CheckError
            gen: Any = await self._invoke_callback(
                cb,
                extra_env=extra_env,
                **options,
            )
            await ctx._consume_gen(gen)
        except Exception as e:
            await self._dispatch_command_failure(
                ctx, e if isinstance(e, KitaError) else CommandRuntimeError(e, cb)
            )
        else:
            await self.app.dispatch(CommandSuccessEvent(self.app, ctx))

    async def _dispatch_command_failure(
        self,
        ctx: Context,
        exc: KitaError,
    ) -> None:
        await self.app.dispatch(CommandFailureEvent(self.app, ctx, exc))


class RestCommandHandler:
    # likely never gonna get implemented
    ...
