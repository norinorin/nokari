import logging

from hikari.events.lifetime_events import StartedEvent, StartingEvent
from hikari.impl.bot import GatewayBot
from hikari.interactions.base_interactions import ResponseType

from kita.command_handlers import GatewayCommandHandler
from kita.data import data
from kita.events import CommandCallEvent, CommandFailureEvent, CommandSuccessEvent
from kita.extensions import listener

_LOGGER = logging.getLogger("testing.extensions.meta")


@listener()
async def on_starting(_: StartingEvent) -> None:
    _LOGGER.info("Starting...")


@listener()
async def on_started(
    event: StartedEvent, handler: GatewayCommandHandler = data(GatewayCommandHandler)
) -> None:
    app = event.app
    assert isinstance(app, GatewayBot)
    _LOGGER.info("It's started! %s %d commands", app.get_me(), len(handler.commands))


@listener()
async def on_command_error(event: CommandFailureEvent) -> None:
    ctx = event.context
    command_name = ctx.command and ctx.command.__name__
    await ctx.respond(f"{command_name} raised an error:\n{event.exception}")
    _LOGGER.error(
        "%s command is failing due to:",
        command_name,
        exc_info=event.exception,
    )


@listener()
async def on_command_call(event: CommandCallEvent) -> None:
    assert event.context.command is not None
    _LOGGER.info("%s command is called!", event.context.command.__name__)


@listener()
async def on_command_success(event: CommandSuccessEvent) -> None:
    assert event.context.command is not None
    _LOGGER.info(
        "%s command invocation successfully completed", event.context.command.__name__
    )
