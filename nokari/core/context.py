"""A module that contains a custom Context class implementation."""

import time
import typing
from types import SimpleNamespace

import hikari
import lightbulb
from hikari import Message, PartialMessage
from hikari import embeds as embeds_
from hikari import files, guilds, snowflakes, undefined, users
from hikari.api import special_endpoints

from nokari.utils.perms import has_channel_perms, has_guild_perms

__all__: typing.Final[typing.List[str]] = ["Context"]


class Context(lightbulb.Context):
    """Custom Context class with overriden methods."""

    parsed_arg: typing.Optional[SimpleNamespace]

    __slots__: typing.List[str] = ["parsed_arg"]

    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        super().__init__(*args, **kwargs)
        self.parsed_arg = None

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
    ) -> Message:
        """Overrides respond method for command invoke on message edit support."""
        if isinstance(embed, hikari.Embed) and not embed.color:
            embed.color = self.color

        if self.parsed_arg and self.parsed_arg.time:
            time_taken = (
                f"That took {round((time.time()-self.parsed_arg.time)*1000, 2)}ms!"
            )
            content = f"{(content or '')[:2000-len(time_taken)-2]}\n\n{time_taken}"

        if (
            resp := self.bot.cache.get_message(
                self.bot.responses_cache.get(self.message_id, 0)
            )
        ) is not None and self.edited_timestamp:
            return await resp.edit(
                content=content or None,
                embed=embed or None,
                attachment=attachment,
                attachments=attachments,
                component=component,
                components=components,
                replace_attachments=True,
                mentions_reply=mentions_reply,
                mentions_everyone=mentions_everyone,
                user_mentions=user_mentions,
                role_mentions=role_mentions,
            )

        if resp is None:
            self.bot.responses_cache.pop(self.message_id, None)

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

        self.bot.responses_cache[self.message_id] = resp.id

        return resp

    @property
    def me(self) -> typing.Optional[hikari.Member]:
        """Returns the Member object of the bot iself if applicable."""
        return (
            self.guild_id
            and self.bot.me
            and self.bot.cache.get_member(self.guild_id, self.bot.me.id)
        )

    def execute_plugins(
        self, func: typing.Callable[[str], None], plugins: str
    ) -> typing.Awaitable[hikari.Message]:
        """A helper methods for loading, unloading, and reloading external plugins."""
        if plugins in ("all", "*"):
            plugins_set = set(self.bot.raw_plugins)
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
                    f"nokari.plugins.{plugin}"
                    if not plugin.startswith("nokari.plugins.")
                    else plugin
                )
            except Exception as _e:  # pylint: disable=broad-except
                self.bot.log.error("Failed to reload %s", plugin, exc_info=_e)
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
            and self.me.top_role
            and (color := self.me.top_role.color) != hikari.Colour.from_rgb(0, 0, 0)
            else self.bot.default_color
        )

    def has_guild_perms(
        self, perms: hikari.Permissions, member: typing.Optional[hikari.Member] = None
    ) -> bool:
        """Returns whether or not a member has certain guild permissions."""
        if member is None:
            if self.me is None:
                raise RuntimeError("Couldn't resolve the Member object of the bot")
            member = self.me

        return has_guild_perms(self.bot, member, perms)

    def has_channel_perms(
        self, perms: hikari.Permissions, member: typing.Optional[hikari.Member] = None
    ) -> bool:
        """
        Returns whether or not a member has certain permissions,
        taking channel overwrites into account.
        """
        if member is None:
            if self.me is None:
                raise RuntimeError("Couldn't resolve the Member object of the bot")
            member = self.me

        return has_channel_perms(self.bot, member, self.channel, perms)
