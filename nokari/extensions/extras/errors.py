import logging
import typing

import hikari
from hikari.interactions.command_interactions import CommandInteraction

from kita.errors import (
    CheckAnyError,
    CheckError,
    CommandOnCooldownError,
    CommandRuntimeError,
    KitaError,
    MissingAnyPermissionsError,
    MissingCommandCallbackError,
    MissingPermissionsError,
)
from kita.events import CommandFailureEvent
from kita.extensions import listener
from kita.utils import find
from nokari.core import Context

_ErrorHandlerT = typing.TypeVar(
    "_ErrorHandlerT",
    bound=typing.Callable[
        [Context, KitaError, hikari.Embed],
        typing.Literal[None],
    ],
)
_LOGGER = logging.getLogger("nokari.plugins.extras.errors")


def handle(
    *errors: Exception,
) -> typing.Callable[[_ErrorHandlerT], _ErrorHandlerT]:
    def decorator(
        func: _ErrorHandlerT,
    ) -> _ErrorHandlerT:
        func.__errors__ = errors  # type: ignore
        return func

    return decorator


handlers: typing.Dict[str, _ErrorHandlerT] = {}


@listener()
async def on_error(event: CommandFailureEvent) -> None:
    """A listener that handles command errors."""
    embed = hikari.Embed()
    interaction = event.context.event.interaction
    assert isinstance(interaction, CommandInteraction)
    embed.set_author(
        name=str(interaction.user),
        icon=interaction.user.avatar_url or interaction.user.default_avatar_url,
    )
    error = event.exception
    class_t = error if hasattr(error, "__mro__") else error.__class__
    func = handlers.get(
        class_t,
        handlers.get(
            parent  # pylint: disable=used-before-assignment
            if (
                parent := find(
                    lambda cls: cls in handlers,
                    class_t.__mro__,
                )
            )
            else None
        ),
    )

    if func:
        func(event.context, error, embed)

    if embed.description:
        await event.context.respond(embed=embed)

    _LOGGER.error(
        "Ignoring exception in command %s",
        event.context.command and event.context.command.__name__,
        exc_info=error,
    )


@handle(CommandOnCooldownError)
def handle_command_on_cooldown(
    _ctx: Context,
    error: CommandOnCooldownError,
    embed: hikari.Embed,
) -> None:
    embed.description = "You're on cooldown"
    embed.set_footer(text=f"Please try again in {round(error.retry_in, 2)} seconds.")


@handle(CommandRuntimeError)
def handle_command_invocation_error(
    _ctx: Context,
    error: CommandRuntimeError,
    embed: hikari.Embed,
) -> None:
    embed.description = str(error.exception)


@handle(MissingPermissionsError)
def handle_missing_required_permission(
    _ctx: Context,
    error: MissingPermissionsError,
    embed: hikari.Embed,
) -> None:
    perms = ", ".join(i.replace("_", " ").lower() for i in str(error.perms).split("|"))
    plural = f"permission{'s' * (len(error.perms) > 1)}"
    embed.description = f"You're missing {perms} {plural} to invoke this command."


@handle(MissingAnyPermissionsError)
def handle_missing_required_permission(
    _ctx: Context,
    error: MissingAnyPermissionsError,
    embed: hikari.Embed,
) -> None:
    perms = ", ".join(i.replace("_", " ").lower() for i in str(error.perms).split("|"))
    embed.description = (
        f"You need to have one of the following perms: {perms} to invoke this command."
    )


@handle(CheckError, MissingCommandCallbackError, CheckAnyError)
def handle_converter_failure(
    _ctx: Context,
    error: KitaError,
    embed: hikari.Embed,
) -> None:
    embed.description = str(error)


# Prevent size change while iterating.
obj = None
err_t = None
for obj in globals().values():
    if hasattr(obj, "__errors__"):
        for err_t in obj.__errors__:
            handlers[err_t] = obj
