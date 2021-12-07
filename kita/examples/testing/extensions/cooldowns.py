from typing import Iterator

from hikari.interactions.base_interactions import ResponseType

from kita.commands import command
from kita.cooldowns import user_hash_getter, with_cooldown
from kita.responses import Response, respond


@command("cooldown", "Cooldown test command.")
@with_cooldown(user_hash_getter, 1, 3)
def cooldown() -> Iterator[Response]:
    bm = cooldown.__bucket_manager__
    assert bm is not None
    yield respond(ResponseType.MESSAGE_CREATE, f"{bm.buckets}, {bm.is_running}")
