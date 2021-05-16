from hikari import (
    GuildMessageCreateEvent,
    GuildMessageDeleteEvent,
    GuildMessageUpdateEvent,
    Message,
)
from lightbulb import Bot, plugins


class Events(plugins.Plugin):
    """
    A plugin that handles events.

    This plugin will process commands on message edits
    and delete the responses if the original messages were deleted.
    """

    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot

    async def handle_ping(self, message: Message) -> None:
        if message.content not in (f"<@{self.bot.me.id}>", f"<@!{self.bot.me.id}>"):
            return

        ctx = self.bot.get_context(
            message,
            message.content,
            invoked_with="prefix",
            invoked_command=self.bot.get_command("prefix"),
        )
        return await self.bot.get_command("prefix").callback(
            self.bot.get_plugin("Config"), ctx
        )

    @plugins.listener()
    async def on_message(self, event: GuildMessageCreateEvent) -> None:
        await self.handle_ping(event.message)

    @plugins.listener()
    async def on_message_edit(self, event: GuildMessageUpdateEvent) -> None:
        if (
            event.is_bot is True
            or (message := self.bot.cache.get_message(event.message_id)) is None
        ):
            return

        message_create_event = (
            GuildMessageCreateEvent(  # pylint: disable=abstract-class-instantiated
                app=event.app, message=message, shard=event.shard
            )
        )
        await self.bot.process_commands_for_event(message_create_event)
        await self.handle_ping(message)

    @plugins.listener()
    async def on_message_delete(self, event: GuildMessageDeleteEvent) -> None:
        if (
            resp := self.bot.cache.get_message(
                self.bot.responses_cache.pop(event.message_id, 0)
            )
        ) is None:
            return

        await resp.delete()


def load(bot: Bot) -> None:
    bot.add_plugin(Events(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Events")
