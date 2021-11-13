import logging
import typing

import hikari
import lightbulb
from lightbulb import BotApp, plugins, utils

# TODO: UnclosedQuotes
from lightbulb.errors import (
    BotMissingRequiredPermission,
    CheckFailure,
    CommandInvocationError,
    CommandIsOnCooldown,
    ConverterFailure,
    MissingRequiredPermission,
    NotEnoughArguments,
)

from nokari.core import Context
from nokari.utils.view import CommandSyntaxError

_ErrorHandlerT = typing.TypeVar(
    "_ErrorHandlerT",
    bound=typing.Callable[
        [Context, lightbulb.errors.LightbulbError, hikari.Embed],
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


errors = plugins.Plugin("Errors")
handlers: typing.Dict[str, _ErrorHandlerT] = {}


@errors.listener(lightbulb.PrefixCommandErrorEvent)
async def on_error(event: lightbulb.PrefixCommandErrorEvent) -> None:
    """A listener that handles command errors."""
    embed = hikari.Embed()
    author = event.context.event.message.author
    embed.set_author(
        name=str(author),
        icon=author.avatar_url or author.default_avatar_url,
    )
    error = event.exception
    class_t = error if hasattr(error, "__mro__") else error.__class__
    func = handlers.get(
        class_t,
        handlers.get(
            parent  # pylint: disable=used-before-assignment
            if (
                parent := utils.find(
                    class_t.__mro__,
                    lambda cls: cls in handlers,
                )
            )
            else None
        ),
    )

    if func:
        func(event.context, error, embed)

    if embed.description:
        await event.context.respond(embed=embed)

    if isinstance(
        error, lightbulb.errors.CommandNotFound
    ) and event.message.content.startswith(error.invoked_with):
        # might not be the best thing to do
        # but since the context will be None if the command wasn't found
        # we'll just assume if the prefix was the same as the command name
        # then it's an empty prefix
        return

    _LOGGER.error(
        "Ignoring exception in command %s",
        event.context.command and event.context.command.name,
        exc_info=error,
    )


@handle(NotEnoughArguments)
def handle_not_enough_arguments(
    ctx: Context,
    error: lightbulb.errors.NotEnoughArguments,
    embed: hikari.Embed,
) -> None:
    """Handles NotEnoughArguments error."""
    embed.description = "Please pass in the required argument."
    embed.add_field(
        name="Usage:",
        value=f"`{ctx.prefix}{ctx.command.signature}`",
    )


@handle(CommandIsOnCooldown)
def handle_command_is_on_cooldown(
    _ctx: Context,
    error: lightbulb.errors.CommandIsOnCooldown,
    embed: hikari.Embed,
) -> None:
    """Handles CommandIsOnCooldown error."""
    embed.description = "You're on cooldown"
    embed.set_footer(text=f"Please try again in {round(error.retry_in, 2)} seconds.")


@handle(CommandInvocationError)
def handle_command_invocation_error(
    ctx: Context,
    error: lightbulb.errors.CommandInvocationError,
    embed: hikari.Embed,
) -> None:
    """Handles CommandInvocationError error."""
    embed.description = str(error.original)


@handle(MissingRequiredPermission)
def handle_missing_required_permission(
    _ctx: Context,
    error: lightbulb.errors.MissingRequiredPermission,
    embed: hikari.Embed,
) -> None:
    """Handles MissingRequiredPermissions error."""
    perms = ", ".join(
        i.replace("_", " ").lower() for i in str(error.permissions).split("|")
    )
    plural = f"permission{'s' * (len(error.permissions) > 1)}"
    embed.description = f"You're missing {perms} {plural} to invoke this command."


@handle(BotMissingRequiredPermission)
def handle_bot_missing_required_permission(
    _ctx: Context,
    error: lightbulb.errors.BotMissingRequiredPermission,
    embed: hikari.Embed,
) -> None:
    """Handles BotMissingPermission error."""
    perms = ", ".join(
        i.replace("_", " ").lower() for i in str(error.permissions).split("|")
    )
    embed.description = (
        f"I'm missing {perms} permission{'s' * (len(error.permissions) > 1)}."
    )


@handle(
    ConverterFailure,
    CheckFailure,
    CommandSyntaxError,
    # UnclosedQuotes,
)
def handle_converter_failure(
    _ctx: Context,
    error: lightbulb.errors.ConverterFailure,
    embed: hikari.Embed,
) -> None:
    """Handles ConverterFailure error."""
    embed.description = error.text


# Prevent size change while iterating.
obj = None
error = None
for obj in globals().values():
    if hasattr(obj, "__errors__"):
        for error in obj.__errors__:
            handlers[error] = obj


def load(bot: BotApp) -> None:
    bot.add_plugin(errors)


def unload(bot: BotApp) -> None:
    bot.remove_plugin("Errors")
