import logging

from hikari.events.lifetime_events import StartedEvent, StartingEvent
from hikari.impl.bot import GatewayBot

from kita.command_handlers import GatewayCommandHandler
from kita.data import data
from kita.extensions import initializer, listener

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


@initializer
def ext_init(handler: GatewayCommandHandler) -> None:
    handler.subscribe(on_started)
    handler.subscribe(on_starting)
