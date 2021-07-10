from contextlib import suppress
import typing

from hikari import (
    GuildMessageCreateEvent,
    GuildMessageDeleteEvent,
    GuildMessageUpdateEvent,
    Message,
)
from hikari.events.interaction_events import InteractionCreateEvent
from hikari.impl.special_endpoints import ActionRowBuilder
from hikari.interactions.bases import ResponseType
from hikari.interactions.component_interactions import ComponentInteraction
from lightbulb import Bot, errors, plugins


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

        with suppress(errors.CommandIsOnCooldown):
            return await self.bot.get_command("prefix").invoke(ctx)

    @plugins.listener()
    async def on_message(self, event: GuildMessageCreateEvent) -> None:
        await self.handle_ping(event.message)

    @plugins.listener()
    async def on_message_edit(self, event: GuildMessageUpdateEvent) -> None:
        if (
            event.is_bot is True
            or (message := self.bot.cache.get_message(event.message_id)) is None
            or event.old_message is None
        ):
            return

        # prevent embed from re-invoking commands
        if event.old_message.content == message.content:
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

    @plugins.listener()
    async def on_interaction_create(self, event: InteractionCreateEvent) -> None:
        """
        This listener handles dead paginators by disabling all the buttons attached to the message.
        """
        if not isinstance(event.interaction, ComponentInteraction):
            return None

        if (
            (interaction := event.interaction)
            and f"{interaction.channel_id}-{interaction.message_id}"
            in self.bot.paginator_ids
        ):
            return None

        if (message := interaction.message) is None:
            return None

        self.bot.log.debug(
            "Handling unhandled interaction create for message %d.", message.id
        )

        components = []

        for idx, component in enumerate(message.components):
            components.append(ActionRowBuilder())
            for button in component.components:  # type: ignore
                kwargs = dict(
                    style=button.style,
                    custom_id=button.custom_id,
                    disabled=True,
                )

                if button.label:
                    kwargs["label"] = button.label

                if button.emoji:
                    kwargs["emoji"] = button.emoji

                if button.url:
                    kwargs["url"] = button.url
                    del kwargs["custom_id"]

                components[idx].add_button(**kwargs)

        await interaction.create_initial_response(
            ResponseType.MESSAGE_UPDATE, components=components
        )

        self.bot.log.debug("Disabled the buttons for message %d.", message.id)


def load(bot: Bot) -> None:
    bot.add_plugin(Events(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Events")
