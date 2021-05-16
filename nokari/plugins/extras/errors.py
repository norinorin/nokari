import typing
from inspect import getmembers
from string import capwords

import hikari
import lightbulb
from lightbulb import Bot, plugins, utils

from nokari.core import Context

_ErrorHandlerT = typing.TypeVar(
    "_ErrorHandlerT",
    bound=typing.Callable[
        [Context, lightbulb.errors.CommandError, hikari.Embed],
        typing.Literal[None],
    ],
)


def aliases(
    *aliases_: str,
) -> typing.Callable[[_ErrorHandlerT], _ErrorHandlerT]:
    def decorator(
        func: _ErrorHandlerT,
    ) -> _ErrorHandlerT:
        func.__aliases__ = aliases_  # type: ignore
        return func

    return decorator


class Errors(plugins.Plugin):
    """A plugin that handles errors."""

    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot
        self.handlers = {}
        for attr, func in getmembers(self):
            if attr.startswith("handle_"):
                self.handlers[capwords(attr[7:], sep="_").replace("_", "")] = func
                if hasattr(func, "__aliases__"):
                    for alias in func.__aliases__:
                        self.handlers[alias] = func

    @plugins.listener(lightbulb.CommandErrorEvent)
    async def on_error(self, event: lightbulb.CommandErrorEvent) -> None:
        """A listener that handles command errors"""
        embed = hikari.Embed()
        author = event.message.author
        embed.set_author(
            name=str(author),
            icon=author.avatar_url or author.default_avatar_url,
        )
        error = event.exception or event.exception.__cause__
        class_t = t if (t := error.__class__) is not type else error
        func = self.handlers.get(
            class_t.__name__,
            self.handlers.get(
                parent.__name__  # pylint: disable=used-before-assignment
                if (
                    parent := utils.find(
                        class_t.__mro__,
                        lambda cls: cls.__name__ in self.handlers,
                    )
                )
                else None
            ),
        )

        if func:
            func(event.context, error, embed)

        if embed.description:
            await event.context.respond(embed=embed)

        self.bot.log.error(
            "Ignoring exception in command %s",
            event.command and event.command.qualified_name,
            exc_info=error,
        )

    @staticmethod
    def handle_not_enough_arguments(
        ctx: Context,
        error: lightbulb.errors.NotEnoughArguments,
        embed: hikari.Embed,
    ) -> None:
        """Handles NotEnoughArguments error"""
        embed.description = "Please pass in the required argument"
        embed.add_field(
            name="Usage:",
            value=f"`{ctx.prefix}{ctx.bot.help_command.get_command_signature(error.command)}`",
        )

    @staticmethod
    def handle_command_is_on_cooldown(
        ctx: Context,
        error: lightbulb.errors.CommandIsOnCooldown,
        embed: hikari.Embed,
    ) -> None:
        """Handles CommandIsOnCooldown error"""
        embed.description = "You're on cooldown"
        embed.set_footer(text=f"Please try again in {round(error.retry_in, 2)} seconds")

    @staticmethod
    def handle_command_invocation_error(
        ctx: Context,
        error: lightbulb.errors.CommandInvocationError,
        embed: hikari.Embed,
    ) -> None:
        """Handles CommandInvocationError error"""
        embed.description = str(error.original)

    @staticmethod
    def handle_missing_required_permission(
        ctx: Context,
        error: lightbulb.errors.MissingRequiredPermission,
        embed: hikari.Embed,
    ) -> None:
        """Handles MissingRequiredPermissions error"""
        perms = ", ".join(i.replace("_", " ").lower() for i in error.missing_perms)
        plural = f"permission{'s' * (len(error.missing_perms) > 1)}"
        embed.description = f"You're missing {perms} {plural} to invoke this command"

    @staticmethod
    def handle_bot_missing_required_permission(
        ctx: Context,
        error: lightbulb.errors.BotMissingRequiredPermission,
        embed: hikari.Embed,
    ) -> None:
        """Handles BotMissingPermission error"""
        perms = ", ".join(i.replace("_", " ").lower() for i in error.missing_perms)
        embed.description = (
            f"I'm missing {perms} permission{'s' * (len(error.missing_perms) > 1)}"
        )

    @staticmethod
    @aliases(
        "UnclosedQuotes",
        "CheckFailure",
        "CommandSyntaxError",
        "_BaseError",  # Errors raised in view.py
    )
    def handle_converter_failure(
        ctx: Context,
        error: lightbulb.errors.ConverterFailure,
        embed: hikari.Embed,
    ) -> None:
        """Handles ConverterFailure error"""
        embed.description = error.text


def load(bot: Bot) -> None:
    bot.add_plugin(Errors(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Errors")
