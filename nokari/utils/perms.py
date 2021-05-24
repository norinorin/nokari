"""A module that contains helper functions for permissions checking."""

import typing
from functools import wraps

import hikari

__all__: typing.Final[typing.List[str]] = [
    "get_guild_perms",
    "has_guild_perms",
    "has_channel_perms",
]
FuncT = typing.TypeVar("FuncT", bound=typing.Callable[..., typing.Any])


def _apply_overwrites(
    perms: hikari.Permissions, allow: hikari.Permissions, deny: hikari.Permissions
) -> hikari.Permissions:
    """Applies overwrites to the permissions."""
    return (perms & ~deny) | allow


def _auto_resolve_guild(func: FuncT) -> FuncT:
    """A decorator that automatically resolves the guild object if it's None."""

    @wraps(func)
    def wrapped(*args: typing.Any) -> typing.Any:
        if len(args) == func.__code__.co_argcount - 1:
            args += (None,)

        if args[-1] is None:
            bot, member, *_, guild = args

            if (
                guild is None
                and (guild := bot.cache.get_guild(member.guild_id)) is None
            ):
                raise RuntimeError("Unable to get the Guild object")

            args = (bot, member, *_, guild)

        return func(*args)

    return typing.cast(FuncT, wrapped)


def _ensure_perms(perms: hikari.Permissions) -> hikari.Permissions:
    """Ensures the permissions."""
    if not perms & hikari.Permissions.SEND_MESSAGES:
        perms &= ~hikari.Permissions.SEND_TTS_MESSAGES
        perms &= ~hikari.Permissions.MENTION_ROLES
        perms &= ~hikari.Permissions.EMBED_LINKS
        perms &= ~hikari.Permissions.ATTACH_FILES

    if not perms & hikari.Permissions.VIEW_CHANNEL:
        perms.value &= ~hikari.Permissions(0b10110011111101111111111101010001)

    return perms


def get_guild_perms(guild: hikari.Guild, member: hikari.Member) -> hikari.Permissions:
    """Returns the guild-wide permissions of a member."""
    ALL = hikari.Permissions(0b111111111111111111111111111111111)

    if guild.owner_id == member.id:
        return ALL

    ret = guild.roles[guild.id].permissions

    for role_id in member.role_ids:
        if (role := guild.get_role(role_id)) is None:
            continue

        ret |= role.permissions

    if ret & hikari.Permissions.ADMINISTRATOR:
        return ALL

    return _ensure_perms(ret)


@_auto_resolve_guild
def has_guild_perms(
    bot: hikari.BotApp,
    member: hikari.Member,
    perms: hikari.Permissions,
    guild: typing.Optional[hikari.Guild] = None,
) -> bool:
    """
    Returns whether or not the member has certain guild permissions.
    This might be overriden by channel overwrites.
    """
    guild = typing.cast(hikari.Guild, guild)
    return (get_guild_perms(guild, member) & perms) == perms


@_auto_resolve_guild
def has_channel_perms(
    bot: hikari.BotApp,
    member: hikari.Member,
    channel: hikari.GuildChannel,
    perms: hikari.Permissions,
    guild: typing.Optional[hikari.Guild] = None,
) -> bool:
    """
    Returns whether or not the member has certain guild permissions
    and is allowed in the channel.
    """
    guild = typing.cast(hikari.Guild, guild)
    base = get_guild_perms(guild, member)

    if everyone := channel.permission_overwrites.get(guild.id):
        base = _apply_overwrites(base, everyone.allow, everyone.deny)

    allow = deny = hikari.Permissions()

    for role_id in member.role_ids:
        if (overwrite := channel.permission_overwrites.get(role_id)) is None:
            continue

        allow |= overwrite.allow
        deny |= overwrite.deny

    base = _apply_overwrites(base, allow, deny)

    if (overwrite := channel.permission_overwrites.get(member.id)) is not None:
        base = _apply_overwrites(base, overwrite.allow, overwrite.deny)

    base = _ensure_perms(base)

    return (base & perms) == perms
