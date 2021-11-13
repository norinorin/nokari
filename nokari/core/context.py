"""A module that contains a custom Context class implementation."""
from __future__ import annotations

import logging
import time
import typing
from types import SimpleNamespace

import hikari
import lightbulb
from hikari import PartialMessage
from hikari import embeds as embeds_
from hikari import files, guilds, snowflakes, undefined, users
from hikari.api import special_endpoints

from nokari.utils.perms import has_channel_perms, has_guild_perms

__all__: typing.Final[typing.List[str]] = ["Context", "PrefixContext"]
_LOGGER = logging.getLogger("nokari.core.context")


class Context(lightbulb.context.Context):
    __slots__ = ()

    @property
    def me(self) -> typing.Optional[hikari.Member]:
        """Returns the Member object of the bot iself if applicable."""
        return (
            self.guild_id
            and (me := self.bot.get_me())
            and self.bot.cache.get_member(self.guild_id, me.id)
        )

    def execute_extensions(
        self, func: typing.Callable[[str], None], plugins: str
    ) -> typing.Awaitable[hikari.Message]:
        """A helper methods for loading, unloading, and reloading extensions."""
        if plugins in ("all", "*"):
            plugins_set = set(self.bot.raw_extensions)
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
            else self.bot.default_color
        )

    def has_guild_perms(
        self, perms: hikari.Permissions, member: typing.Optional[hikari.Member] = None
    ) -> bool:
        """Returns whether or not a member has certain guild permissions."""

        if (member := member or self.me) is None:
            raise RuntimeError("Couldn't resolve the Member object of the bot")

        return has_guild_perms(self.bot, member, perms)

    def has_channel_perms(
        self, perms: hikari.Permissions, member: typing.Optional[hikari.Member] = None
    ) -> bool:
        """
        Returns whether or not a member has certain permissions,
        taking channel overwrites into account.
        """
        if (member := member or self.me) is None:
            raise RuntimeError("Couldn't resolve the Member object of the bot")

        return has_channel_perms(self.bot, member, self.channel, perms)


class PrefixContext(Context, lightbulb.context.PrefixContext):
    """Custom Context class with overriden methods."""

    __slots__: typing.List[str] = ["parsed_arg", "interaction"]

    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        super().__init__(*args, **kwargs)
        self.parsed_arg: SimpleNamespace | None = None
        self.interaction: hikari.ComponentInteraction | None = None

    async def respond(  # pylint: disable=arguments-differ,too-many-locals
        self,
        content: undefined.UndefinedOr[typing.Any] = undefined.UNDEFINED,
        *,
        attachment: undefined.UndefinedOr[files.Resourceish] = undefined.UNDEFINED,
        attachments: undefined.UndefinedOr[
            typing.Sequence[files.Resourceish]
        ] = undefined.UNDEFINED,
        component: undefined.UndefinedOr[
            special_endpoints.ComponentBuilder
        ] = undefined.UNDEFINED,
        components: undefined.UndefinedOr[
            typing.Sequence[special_endpoints.ComponentBuilder]
        ] = undefined.UNDEFINED,
        embed: undefined.UndefinedOr[embeds_.Embed] = undefined.UNDEFINED,
        embeds: undefined.UndefinedOr[
            typing.Sequence[embeds_.Embed]
        ] = undefined.UNDEFINED,
        nonce: undefined.UndefinedOr[str] = undefined.UNDEFINED,
        tts: undefined.UndefinedOr[bool] = undefined.UNDEFINED,
        reply: typing.Union[
            undefined.UndefinedType, snowflakes.SnowflakeishOr[PartialMessage], bool
        ] = undefined.UNDEFINED,
        mentions_everyone: undefined.UndefinedOr[bool] = undefined.UNDEFINED,
        mentions_reply: undefined.UndefinedOr[bool] = undefined.UNDEFINED,
        user_mentions: undefined.UndefinedOr[
            typing.Union[snowflakes.SnowflakeishSequence[users.PartialUser], bool]
        ] = undefined.UNDEFINED,
        role_mentions: undefined.UndefinedOr[
            typing.Union[snowflakes.SnowflakeishSequence[guilds.PartialRole], bool]
        ] = undefined.UNDEFINED,
    ) -> lightbulb.context.ResponseProxy:
        """Overrides respond method for command invoke on message edit support."""
        if isinstance(embed, hikari.Embed) and embed.color is None:
            embed.color = self.color

        if embeds:
            for embed_ in embeds:
                if embed_.color is None:
                    embed_.color = self.color

        if self.parsed_arg and self.parsed_arg.time:
            time_taken = (
                f"That took {round((time.time()-self.parsed_arg.time)*1000, 2)}ms!"
            )
            content = f"{(content or '')[:2000-len(time_taken)-2]}\n\n{time_taken}"

        if self.interaction:
            # assume it's been deferred
            await self.interaction.edit_initial_response(
                content=content or None,
                embed=embed or None,
                attachment=attachment,
                attachments=attachments,
                components=components or [],
                mentions_everyone=mentions_everyone,
                user_mentions=user_mentions,
                role_mentions=role_mentions,
            )
            return self.interaction.message

        if (
            resp := self.bot.cache.get_message(
                self.bot.responses_cache.get(self.event.message_id, 0)
            )
        ) is not None and self.edited_timestamp:
            return await resp.edit(
                content=content or None,
                embed=embed or None,
                attachment=attachment,
                attachments=attachments,
                component=component or None,
                replace_attachments=True,
                mentions_reply=mentions_reply,
                mentions_everyone=mentions_everyone,
                user_mentions=user_mentions,
                role_mentions=role_mentions,
            )

        if resp is None:
            self.bot.responses_cache.pop(self.event.message_id, None)

        resp = await super().respond(
            content=content,
            embed=embed,
            embeds=embeds,
            component=component,
            components=components,
            attachment=attachment,
            attachments=attachments,
            nonce=nonce,
            tts=tts,
            reply=reply,
            mentions_everyone=mentions_everyone,
            user_mentions=user_mentions,
            role_mentions=role_mentions,
            mentions_reply=mentions_reply,
        )

        self.bot.responses_cache[self.event.message_id] = (await resp.message()).id

        return resp

    async def invoke(self) -> None:
        if getattr(self.command, "disabled", False):
            return None
        return await super().invoke()
