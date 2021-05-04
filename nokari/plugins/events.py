from hikari import (
    GuildMessageCreateEvent,
    GuildMessageDeleteEvent,
    GuildMessageUpdateEvent,
)
from lightbulb import Bot, plugins


class Events(plugins.Plugin):
    """
    A plugin that handles events.

    This plugin will process commands on message edits
    and delete the responses if the original message was deleted.
    """

    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot

    @plugins.listener()
    async def on_message_edit(self, event: GuildMessageUpdateEvent) -> None:
        if (
            event.is_bot is True
            or (message := self.bot.cache.get_message(event.message_id)) is None
        ):
            return

        message_create_event = GuildMessageCreateEvent(
            app=event.app, message=message, shard=event.shard
        )
        await self.bot.process_commands_for_event(message_create_event)

    @plugins.listener()
    async def on_message_delete(self, event: GuildMessageDeleteEvent) -> None:
        resp = self.bot.cache.get_message(self.bot._resp_cache.get(event.message_id, 0))

        if resp is None:
            return

        await resp.delete()


def load(bot: Bot) -> None:
    bot.add_plugin(Events(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Events")
