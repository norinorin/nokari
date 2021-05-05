import typing
from inspect import getmembers
from string import capwords

import hikari
import lightbulb
from lightbulb import Bot, plugins

from nokari.core import Context
from nokari.utils import plural

_ErrorHandler = typing.Callable[
    ["Errors", Context, lightbulb.errors.CommandError, hikari.Embed],
    typing.Literal[None],
]


def aliases(
    *aliases: str,
) -> typing.Callable[[_ErrorHandler], _ErrorHandler]:
    def decorator(
        func: _ErrorHandler,
    ) -> _ErrorHandler:
        func.__aliases__ = aliases  # type: ignore
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
            name=author.username,
            icon=author.avatar_url or author.default_avatar_url,
        )
        error = event.exception or event.exception.__cause__
        func = self.handlers.get(error.__class__.__name__)

        if func:
            func(event.context, error, embed)

        if embed.description:
            await event.context.respond(embed=embed)

        self.bot.log.error(
            "Ignoring exception in command %s", event.command, exc_info=error
        )

    def handle_not_enough_arguments(
        self,
        ctx: Context,
        error: lightbulb.errors.NotEnoughArguments,
        embed: hikari.Embed,
    ) -> None:
        """Handles NotEnoughArguments error"""
        embed.description = "Please pass in the required argument"
        embed.add_field(
            name="Usage:",
            value=f"`{ctx.prefix}{self.bot.help_command.get_command_signature(error.command)}`",
        )

    def handle_command_is_on_cooldown(
        self,
        ctx: Context,
        error: lightbulb.errors.CommandIsOnCooldown,
        embed: hikari.Embed,
    ) -> None:
        """Handles CommandIsOnCooldown error"""
        embed.description = "You're on cooldown"
        embed.set_footer(
            text=f"Please try again in {round(error.retry_after, 2)} seconds"
        )

    def handle_command_invocation_error(
        self,
        ctx: Context,
        error: lightbulb.errors.CommandInvocationError,
        embed: hikari.Embed,
    ) -> None:
        """Handles CommandInvocationError error"""
        embed.description = str(error.original)

    def handle_missing_required_permission(
        self,
        ctx: Context,
        error: lightbulb.errors.MissingRequiredPermission,
        embed: hikari.Embed,
    ) -> None:
        """Handles MissingRequiredPermissions error"""
        embed.description = f"You're missing {', '.join(i.replace('_', ' ').lower() for i in error.missing_perms)} permission{'s' * (len(error.missing_perms) > 1)} to invoke this command"

    def handle_bot_missing_required_permission(
        self,
        ctx: Context,
        error: lightbulb.errors.BotMissingRequiredPermission,
        embed: hikari.Embed,
    ) -> None:
        """Handles BotMissingPermission error"""
        embed.description = f"I'm missing {', '.join(i.replace('_', ' ').lower() for i in error.missing_perms)} permission{'s' * (len(error.missing_perms) > 1)}"

    @aliases(
        "CommandSyntaxError",
        "CheckFailure",
        "OnlyInGuild",
        "OnlyInDM",
        "BotOnly",
        "HumanOnly",
        "NSFWChannelOnly",
        "MissingRequiredRole",
    )
    def handle_converter_failure(
        self,
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
