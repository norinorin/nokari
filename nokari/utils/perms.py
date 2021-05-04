"""A module that contains helper functions for permissions checking."""

import typing

import hikari

__all__: typing.Final[typing.List[str]] = ["has_guild_perms"]


def has_guild_perms(
    bot: hikari.BotApp, member: hikari.Member, perms: hikari.Permissions
) -> bool:
    """
    Returns whether or not the member has certain guild permissions.
    This might be overriden by channel overwrites.
    """
    if (guild := bot.cache.get_guild(member.guild_id)) and member.id == guild.owner_id:
        return True

    for role_id in member.role_ids:

        role = bot.cache.get_role(role_id)

        if role is None:
            continue

        if (
            role.permissions & hikari.Permissions.ADMINISTRATOR
            or (role.permissions & perms) == perms
        ):
            return True

    return False
