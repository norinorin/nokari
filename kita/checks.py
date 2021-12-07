from typing import Any, Callable, Literal, MutableMapping, Type, cast

from hikari.events.interaction_events import InteractionCreateEvent
from hikari.interactions.command_interactions import CommandInteraction
from hikari.permissions import Permissions

from kita.command_handlers import GatewayCommandHandler
from kita.data import data
from kita.errors import (
    CheckAnyError,
    DMOnlyError,
    GuildOnlyError,
    MissingAnyPermissionsError,
    MissingPermissionsError,
    OwnerOnlyError,
)
from kita.typedefs import CallableProto, ICommandCallback
from kita.utils import ensure_checks

__all__ = (
    "with_check",
    "with_check_any",
    "guild_only",
    "dm_only",
    "owner_only",
    "has_all_permissions",
    "has_any_permissions",
)


def with_check(
    predicate: CallableProto,
) -> Callable[[CallableProto], ICommandCallback]:
    def decorator(_command: CallableProto) -> ICommandCallback:
        command = cast(ICommandCallback, _command)
        ensure_checks(command)
        command.__checks__.append(predicate)
        return command

    return decorator


def with_check_any(
    *predicates: CallableProto,
) -> Callable[[CallableProto], ICommandCallback]:
    async def _inner(
        handler: GatewayCommandHandler = data(GatewayCommandHandler),
        event: InteractionCreateEvent = data(InteractionCreateEvent),
        interaction: CommandInteraction = data(CommandInteraction),
    ) -> Literal[True]:
        exceptions = []
        extra_env: MutableMapping[Type[Any], Any] = {
            InteractionCreateEvent: event,
            CommandInteraction: interaction,
        }
        for predicate in predicates:
            try:
                if await handler._invoke_callback(predicate, extra_env=extra_env):
                    return True
            except Exception as exc:
                exceptions.append(exc)

        raise CheckAnyError(predicates, exceptions)

    return with_check(_inner)


def guild_only(
    interaction: CommandInteraction = data(CommandInteraction),
) -> Literal[True]:
    if interaction.guild_id is None:
        raise GuildOnlyError(f"command {interaction.command_name!r} is guild only.")
    return True


def dm_only(
    interaction: CommandInteraction = data(CommandInteraction),
) -> Literal[True]:
    if interaction.guild_id is not None:
        raise DMOnlyError(f"command {interaction.command_name!r} is dm only.")
    return True


def owner_only(
    interaction: CommandInteraction = data(CommandInteraction),
    handler: GatewayCommandHandler = data(GatewayCommandHandler),
) -> Literal[True]:
    if interaction.user.id not in handler.owner_ids:
        raise OwnerOnlyError("command {interaction.command_name!r} is owner only.")
    return True


def has_all_permissions(perms: Permissions) -> CallableProto:
    def inner(
        interaction: CommandInteraction = data(CommandInteraction),
    ) -> Literal[True]:
        if not (member := interaction.member) or (member.permissions & perms) != perms:
            raise MissingPermissionsError(perms)
        return True

    return inner


def has_any_permissions(perms: Permissions) -> CallableProto:
    def inner(
        interaction: CommandInteraction = data(CommandInteraction),
    ) -> Literal[True]:
        if not ((member := interaction.member) and member.permissions & perms):
            raise MissingAnyPermissionsError(perms)
        return True

    return inner
