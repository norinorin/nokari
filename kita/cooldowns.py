from typing import Any, Callable, Union, cast, overload

from hikari.events.interaction_events import InteractionCreateEvent
from hikari.interactions.command_interactions import CommandInteraction
from hikari.snowflakes import Snowflakeish

from kita.buckets import BucketManager
from kita.typedefs import CallableProto, HashGetter, ICommandCallback
from kita.utils import ensure_bucket_manager, is_command

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


@overload
def with_cooldown(
    arg: ICommandCallback, /
) -> Callable[[CallableProto], ICommandCallback]:
    ...


@overload
def with_cooldown(
    arg: HashGetter, /, limit: int, period: float
) -> Callable[[CallableProto], ICommandCallback]:
    ...


def with_cooldown(
    arg: Union[ICommandCallback, HashGetter],
    /,
    limit: Any = None,
    period: Any = None,
) -> Callable[[CallableProto], ICommandCallback]:
    def decorator(callback: CallableProto) -> ICommandCallback:
        callback = cast(ICommandCallback, callback)
        if is_command(arg):
            manager = ensure_bucket_manager(arg).__bucket_manager__
        else:
            manager = BucketManager(callback.__name__, arg, limit, period)
        callback.__bucket_manager__ = manager
        return callback

    return decorator
