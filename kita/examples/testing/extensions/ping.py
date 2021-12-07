from typing import Iterator

from hikari.impl.bot import GatewayBot
from hikari.interactions.base_interactions import ResponseType

from kita.commands import command
from kita.data import data
from kita.responses import Response, respond


@command("ping", "Responds with the latency!")
def ping(
    app: GatewayBot = data(GatewayBot),
) -> Iterator[Response]:
    yield respond(
        ResponseType.MESSAGE_CREATE, f"Latency: {int(app.heartbeat_latency * 1000)}ms"
    )
