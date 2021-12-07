from typing import Callable, cast

from hikari.events.interaction_events import InteractionCreateEvent
from hikari.interactions.command_interactions import CommandInteraction
from hikari.snowflakes import Snowflakeish

from kita.buckets import BucketManager
from kita.typedefs import CallableProto, HashGetter, ICommandCallback
from kita.utils import ensure_bucket_manager

__all__ = (
    "with_cooldown",
    "global_hash_getter",
    "user_hash_getter",
    "guild_hash_getter",
    "channel_hash_getter",
)


def _get_command_interaction(event: InteractionCreateEvent) -> CommandInteraction:
    interaction = event.interaction
    assert isinstance(interaction, CommandInteraction)
    return interaction


def global_hash_getter(_: InteractionCreateEvent) -> Snowflakeish:
    return 0


def user_hash_getter(event: InteractionCreateEvent) -> Snowflakeish:
    interaction = _get_command_interaction(event)
    return interaction.user.id


def guild_hash_getter(event: InteractionCreateEvent) -> Snowflakeish:
    interaction = _get_command_interaction(event)
    return interaction.guild_id or interaction.channel_id


def channel_hash_getter(event: InteractionCreateEvent) -> Snowflakeish:
    interaction = _get_command_interaction(event)
    return interaction.channel_id


def with_cooldown(
    hash_getter: HashGetter, limit: int, period: float
) -> Callable[[CallableProto], ICommandCallback]:
    def decorator(callback: CallableProto) -> ICommandCallback:
        callback = cast(ICommandCallback, callback)
        ensure_bucket_manager(callback)
        callback.__bucket_manager__ = BucketManager(hash_getter, limit, period)
        return callback

    return decorator
