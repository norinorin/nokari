"""A module that contains a custom Context class implementation."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

import hikari

from kita.contexts import Context as Context_
from nokari.utils.perms import has_channel_perms, has_guild_perms

__all__ = ("Context",)
_LOGGER = logging.getLogger("nokari.core.context")


class Context(Context_):
    __slots__ = ()

    @property
    def me(self) -> Optional[hikari.Member]:
        """Returns the Member object of the bot iself if applicable."""
        return (
            self.interaction.guild_id
            and (me := self.handler.app.get_me())
            and self.handler.app.cache.get_member(self.interaction.guild_id, me.id)
        )

    def execute_extensions(
        self, func: Callable[[str], None], plugins: str
    ) -> Awaitable[hikari.Message]:
        """A helper methods for loading, unloading, and reloading extensions."""
        if plugins in ("all", "*"):
            plugins_set = set(self.app.raw_extensions)
        else:
            plugins_set = set(
                sum(
                    [
                        [o] if (o := i.strip()) and " " not in o else o.split()
                        for i in plugins.split(",")
                    ],
                    [],
                )
            )
        failed = set()
        for plugin in plugins_set:
            try:
                func(
                    f"nokari.extensions.{plugin}"
                    if not plugin.startswith("nokari.extensions.")
                    else plugin
                )
            except Exception as _e:  # pylint: disable=broad-except
                _LOGGER.error("Failed to reload %s", plugin, exc_info=_e)
                failed.add((plugin, _e.__class__.__name__))

        key = lambda s: (len(s), s)
        loaded = "\n".join(
            f"+ {i}" for i in sorted(plugins_set ^ {x[0] for x in failed}, key=key)
        )
        failed = "\n".join(f"- {c} {e}" for c, e in sorted(failed, key=key))
        return self.respond(f"```diff\n{loaded}\n{failed}```")

    @property
    def color(self) -> hikari.Colour:
        """
        Returns the top role color of the bot itself if has one,
        otherwise the default color
        """
        return (
            color
            if self.me
            and (top_role := self.me.get_top_role())
            and (color := top_role.color) != hikari.Colour.from_rgb(0, 0, 0)
            else self.handler.app.default_color  # type: ignore
        )

    def has_guild_perms(
        self, perms: hikari.Permissions, member: Optional[hikari.Member] = None
    ) -> bool:
        """Returns whether or not a member has certain guild permissions."""

        if (member := member or self.me) is None:
            raise RuntimeError("Couldn't resolve the Member object of the bot")

        return has_guild_perms(self.app, member, perms)

    def has_channel_perms(
        self, perms: hikari.Permissions, member: Optional[hikari.Member] = None
    ) -> bool:
        """
        Returns whether or not a member has certain permissions,
        taking channel overwrites into account.
        """
        if (member := member or self.me) is None:
            raise RuntimeError("Couldn't resolve the Member object of the bot")

        return has_channel_perms(self.app, member, self.channel, perms)
