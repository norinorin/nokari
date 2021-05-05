import lightbulb
from lightbulb import Bot, plugins


class Errors(plugins.Plugin):
    """A plugin that handles errors."""

    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot

    @plugins.listener(lightbulb.CommandErrorEvent)
    async def on_error(self, event: lightbulb.CommandErrorEvent) -> None:
        """A listener that handles command errors"""
        error = event.exception or event.exception.__cause__
        if isinstance(error, lightbulb.errors.NotEnoughArguments):
            await event.message.respond("Insufficient arguments")
        elif isinstance(error, lightbulb.errors.CommandIsOnCooldown):
            await event.message.respond(
                f"Command on cooldown, retry in {error.retry_in:.2f}s"
            )
        elif isinstance(error, lightbulb.errors.CommandNotFound):
            pass
        else:
            self.bot.log.error(
                "Ignoring exception in command %s", event.command, exc_info=error
            )


def load(bot: Bot) -> None:
    bot.add_plugin(Errors(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Errors")
