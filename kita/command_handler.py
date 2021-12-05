import inspect
import logging
import typing as t
from types import AsyncGeneratorType, GeneratorType

from hikari.api.special_endpoints import CommandBuilder
from hikari.events.interaction_events import InteractionCreateEvent
from hikari.events.lifetime_events import StartedEvent
from hikari.impl.bot import GatewayBot
from hikari.interactions.base_interactions import InteractionType
from hikari.interactions.command_interactions import CommandInteraction
from hikari.snowflakes import Snowflake
from hikari.undefined import UNDEFINED, UndefinedOr

from kita.commands import command
from kita.data import DataContainerMixin
from kita.responses import Response
from kita.typedefs import (
    CommandCallback,
    CommandContainer,
    ICommandCallback,
    IGroupCommandCallback,
)
from kita.utils import get_command_builder

__all__ = ("GatewayCommandHandler",)
_LOGGER = logging.getLogger("kita.command_handler")


class GatewayCommandHandler(DataContainerMixin):
    def __init__(
        self, app: GatewayBot, guild_ids: t.Optional[t.Set[Snowflake]] = None
    ) -> None:
        super().__init__()
        self.app = app
        self.set_data(app)
        self._commands: CommandContainer = {}
        self.guild_ids = guild_ids or set()
        app.subscribe(StartedEvent, self._on_started)
        app.subscribe(InteractionCreateEvent, self._process_command_interaction)

    @property
    def commands(self) -> CommandContainer:
        return self._commands

    def command(
        self,
        name: str,
        description: str,
        guild_ids: UndefinedOr[t.Set[Snowflake]] = UNDEFINED,
    ) -> t.Callable[[CommandCallback], CommandCallback]:
        def decorator(func: CommandCallback) -> CommandCallback:
            self.add_command(func := command(name, description, guild_ids)(func))
            return func

        return decorator

    def add_command(self, func: CommandCallback, /) -> None:
        self._commands[func.__name__] = func

    def remove_command(self, func_or_name: t.Union[CommandCallback, str]) -> None:
        if not isinstance(func_or_name, str):
            func_or_name = func_or_name.__name__

        del self._commands[func_or_name]

    async def _on_started(self, _: StartedEvent) -> None:
        return await self._sync()

    async def _sync(self) -> None:
        commands: t.List[CommandBuilder] = []
        guild_commands: t.MutableMapping[Snowflake, t.List[CommandBuilder]] = {}
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
    ) -> t.Tuple[ICommandCallback, t.Dict[str, t.Any]]:
        options = interaction.options
        cb: ICommandCallback = self._commands[interaction.command_name]

        while options and (option := options[0]).type in (1, 2):
            cb = t.cast(IGroupCommandCallback, cb).__sub_commands__[option.name]
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

        gen: t.Union[AsyncGeneratorType, GeneratorType] = await self._invoke_callback(
            cb,
            {InteractionCreateEvent: event, CommandInteraction: event.interaction},
            **options,
        )

        if async_gen := inspect.isasyncgen(gen):
            send = gen.asend
        elif inspect.isgenerator(gen):
            send = gen.send
        elif inspect.iscoroutine(gen):
            await gen
            return
        else:
            return

        sent = None

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
                    sent = None
        except (StopIteration, StopAsyncIteration):
            pass


class RestCommandHandler:
    ...
