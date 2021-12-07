from __future__ import annotations

import inspect
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

from kita.commands import command
from kita.data import DataContainerMixin
from kita.errors import (
    CommandNameConflictError,
    CommandRuntimeError,
    ExtensionFinalizationError,
    ExtensionInilizationError,
)
from kita.events import CommandCallEvent, CommandFailureEvent, CommandSuccessEvent
from kita.extensions import listener, load_extension, reload_extension, unload_extension
from kita.responses import Response
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
    def __init__(
        self, app: GatewayBot, guild_ids: Optional[Set[Snowflakeish]] = None
    ) -> None:
        super().__init__()
        self.app = app
        self.set_data(app)
        self._commands: CommandContainer = {}
        self._extensions: Dict[str, Extension] = {}
        self.guild_ids = guild_ids or set()
        self._listeners: MutableMapping[
            EventCallback, CallbackT
        ] = WeakValueDictionary()
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

    def _load_module(self, mod: Extension) -> None:
        name = mod.__name__
        try:
            mod.__einit__(self)
        except Exception as e:
            unload_extension(name)
            raise ExtensionInilizationError(e, mod) from e
        else:
            self._extensions[name] = mod

    def _unload_module(self, mod: Extension) -> None:
        name = mod.__name__
        try:
            mod.__edel__(self)
        except Exception as e:
            load_extension(name)
            raise ExtensionFinalizationError(e, mod) from e
        else:
            del self._extensions[name]

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
        return await self._sync()

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

        _LOGGER.debug("Got the callback %s and options %s", cb.__name__, cb.options)
        return cb, {o.name: o.value for o in options or []}

    async def _process_command_interaction(self, event: InteractionCreateEvent) -> None:

        if (
            interaction := event.interaction
        ).type is not InteractionType.APPLICATION_COMMAND:
            return

        assert isinstance(interaction, CommandInteraction)

        _LOGGER.debug("Received options: %s", interaction.options)

        try:
            cb, options = self._resolve_cb(interaction)
        except KeyError as err:
            raise RuntimeError("Callback wasn't found") from err

        gen: Any = await self._invoke_callback(
            cb,
            extra_env={
                InteractionCreateEvent: event,
                CommandInteraction: event.interaction,
            },
            **options,
        )

        await self.app.dispatch(CommandCallEvent(self.app, self, event, cb))

        try:
            await self._consume_gen(gen, event)
        except Exception as e:
            await self.app.dispatch(
                CommandFailureEvent(
                    self.app, self, event, cb, CommandRuntimeError(e, cb)
                )
            )
        else:
            await self.app.dispatch(CommandSuccessEvent(self.app, self, event, cb))

    @staticmethod
    async def _consume_gen(
        gen: Any,
        event: InteractionCreateEvent,
    ) -> None:
        if async_gen := inspect.isasyncgen(gen):
            send = gen.asend
        elif inspect.isgenerator(gen):
            send = gen.send
        elif inspect.iscoroutine(gen):
            await gen
            return
        else:
            return

        sent: Any = None

        try:
            while 1:
                val = send(sent)

                if async_gen:
                    val = await val

                _LOGGER.debug("Got %s from generator", val)

                if isinstance(val, Response):
                    sent = await val.execute(event)
                elif inspect.iscoroutine(val):
                    sent = await val
                else:
                    sent = val
        except (StopIteration, StopAsyncIteration):
            pass


class RestCommandHandler:
    # likely never gonna get implemented
    ...
