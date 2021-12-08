from typing import Iterator, Optional

from kita.commands import command
from kita.cooldowns import user_hash_getter, with_cooldown
from kita.responses import Response, respond


@command("cooldown", "Cooldown test command.")
@with_cooldown(user_hash_getter, 3, 10)
def cooldown() -> Optional[Response]:
    bm = cooldown.__bucket_manager__
    assert bm is not None
    return respond(f"{bm.buckets}, {bm.is_running}")
