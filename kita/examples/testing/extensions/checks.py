from typing import Iterator

from hikari.interactions.base_interactions import ResponseType
from hikari.permissions import Permissions

from kita.checks import has_any_permissions, owner_only, with_check, with_check_any
from kita.commands import command
from kita.responses import Response, respond


@command("owner", "Owner only test command")
@with_check(owner_only)
def owner() -> Iterator[Response]:
    yield respond(ResponseType.MESSAGE_CREATE, "Owner check passed (with_check).")


@command("owner_or_perm", "Owner or perm test command")
@with_check_any(owner_only, has_any_permissions(Permissions.SEND_MESSAGES))
def owner_or_perm() -> Iterator[Response]:
    yield respond(ResponseType.MESSAGE_CREATE, "Owner or perm passed (with_any_check).")
