import logging
import typing
from inspect import getmembers

import hikari
import lightbulb
from lightbulb import Bot, plugins, utils
from lightbulb.errors import (
    BotMissingRequiredPermission,
    CheckFailure,
    CommandInvocationError,
    CommandIsOnCooldown,
    CommandSyntaxError,
    ConverterFailure,
    MissingRequiredPermission,
    NotEnoughArguments,
    UnclosedQuotes,
)

from nokari.core import Context

_ErrorHandlerT = typing.TypeVar(
    "_ErrorHandlerT",
    bound=typing.Callable[
        [Context, lightbulb.errors.CommandError, hikari.Embed],
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


class Errors(plugins.Plugin):
    """A plugin that handles errors."""

    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot
        self.handlers = {}
        for _, func in getmembers(self):
            for error in getattr(func, "__errors__", []):
                self.handlers[error] = func

    @plugins.listener(lightbulb.CommandErrorEvent)
    async def on_error(self, event: lightbulb.CommandErrorEvent) -> None:
        """A listener that handles command errors."""
        embed = hikari.Embed()
        author = event.message.author
        embed.set_author(
            name=str(author),
            icon=author.avatar_url or author.default_avatar_url,
        )
        error = event.exception
        class_t = error if hasattr(error, "__mro__") else error.__class__
        func = self.handlers.get(
            class_t,
            self.handlers.get(
                parent  # pylint: disable=used-before-assignment
                if (
                    parent := utils.find(
                        class_t.__mro__,
                        lambda cls: cls in self.handlers,
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
            event.command and event.command.qualified_name,
            exc_info=error,
        )

    @staticmethod
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
            value=f"`{ctx.prefix}{ctx.bot.help_command.get_command_signature(error.command)}`",
        )

    @staticmethod
    @handle(CommandIsOnCooldown)
    def handle_command_is_on_cooldown(
        _ctx: Context,
        error: lightbulb.errors.CommandIsOnCooldown,
        embed: hikari.Embed,
    ) -> None:
        """Handles CommandIsOnCooldown error."""
        embed.description = "You're on cooldown"
        embed.set_footer(
            text=f"Please try again in {round(error.retry_in, 2)} seconds."
        )

    @staticmethod
    @handle(CommandInvocationError)
    def handle_command_invocation_error(
        ctx: Context,
        error: lightbulb.errors.CommandInvocationError,
        embed: hikari.Embed,
    ) -> None:
        """Handles CommandInvocationError error."""
        embed.description = str(error.original)

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    @handle(ConverterFailure, UnclosedQuotes, CheckFailure, CommandSyntaxError)
    def handle_converter_failure(
        _ctx: Context,
        error: lightbulb.errors.ConverterFailure,
        embed: hikari.Embed,
    ) -> None:
        """Handles ConverterFailure error."""
        embed.description = error.text


def load(bot: Bot) -> None:
    bot.add_plugin(Errors(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Errors")
