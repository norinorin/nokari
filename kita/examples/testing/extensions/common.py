from typing import Iterator

from hikari.impl.bot import GatewayBot
from hikari.interactions.base_interactions import ResponseType
from psutil import Process

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


@command("rss", "Responds with the RSS of the app.")
def rss(process: Process = data(Process)) -> Iterator[Response]:
    rss = process.memory_full_info().rss
    yield respond(ResponseType.MESSAGE_CREATE, f"{round(rss / 1_024 ** 2, 2)}MiB")
