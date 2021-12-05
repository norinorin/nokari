import logging
import typing as t

from hikari.api.special_endpoints import CommandBuilder
from hikari.events.interaction_events import InteractionCreateEvent
from hikari.events.lifetime_events import StartingEvent
from hikari.impl.bot import GatewayBot
from hikari.interactions.base_interactions import InteractionType
from hikari.interactions.command_interactions import CommandInteraction
from hikari.snowflakes import Snowflake
from hikari.undefined import UNDEFINED, UndefinedOr

from kita.commands import command
from kita.typedefs import CommandCallback, CommandContainer
from kita.utils import get_command_builder

__all__ = ("GatewayCommandHandler",)
_LOGGER = logging.getLogger("kita.command_handler")


class GatewayCommandHandler:
    def __init__(
        self, app: GatewayBot, guild_ids: t.Optional[t.Set[Snowflake]] = None
    ) -> None:
        self.app = app
        self._commands: CommandContainer = {}
        self.guild_ids = guild_ids or set()
        app.subscribe(StartingEvent, self._on_starting)

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

    def _on_starting(self, _: StartingEvent) -> t.Coroutine[t.Any, t.Any, None]:
        return self._sync()

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

    async def _process_command_interaction(self, event: InteractionCreateEvent) -> None:
        if not event.interaction.type is InteractionType.APPLICATION_COMMAND:
            return

        assert isinstance(event.interaction, CommandInteraction)

        _LOGGER.debug("Received options: %s", event.interaction.options)


class RestCommandHandler:
    ...
