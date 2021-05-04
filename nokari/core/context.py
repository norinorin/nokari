import typing

import hikari
import lightbulb
from hikari import Color, Message
from hikari import embeds as embeds_
from hikari import files, guilds, snowflakes, undefined, users

from nokari.core.paginator import Paginator

__all__: typing.Final[typing.List[str]] = ["Context"]
_ContextArguments = typing.Union[lightbulb.Bot, Message, str, lightbulb.Command]


class Context(lightbulb.Context):
    __slots__: typing.Tuple[str] = ("no_embed",)

    def __init__(
        self,
        *args: _ContextArguments,
        **kwargs: _ContextArguments,
    ) -> None:
        super().__init__(*args, **kwargs)

    async def respond(
        self,
        content: undefined.UndefinedOr[typing.Any] = undefined.UNDEFINED,
        *,
        embed: undefined.UndefinedOr[embeds_.Embed] = undefined.UNDEFINED,
        attachment: undefined.UndefinedOr[files.Resourceish] = undefined.UNDEFINED,
        attachments: undefined.UndefinedOr[
            typing.Sequence[files.Resourceish]
        ] = undefined.UNDEFINED,
        tts: undefined.UndefinedOr[bool] = undefined.UNDEFINED,
        nonce: undefined.UndefinedOr[str] = undefined.UNDEFINED,
        mentions_everyone: undefined.UndefinedOr[bool] = undefined.UNDEFINED,
        user_mentions: undefined.UndefinedOr[
            typing.Union[
                typing.Collection[snowflakes.SnowflakeishOr[users.PartialUser]], bool
            ]
        ] = undefined.UNDEFINED,
        role_mentions: undefined.UndefinedOr[
            typing.Union[
                typing.Collection[snowflakes.SnowflakeishOr[guilds.PartialRole]], bool
            ]
        ] = undefined.UNDEFINED,
        paginator: typing.Optional[Paginator] = None,
    ) -> Message:
        """Overrides respond method for command invoke on nessage edits support"""
        if isinstance(embed, hikari.Embed) and not embed.color:
            embed.color = Color(0x0F000)

        resp = self.bot.cache.get_message(self.bot._resp_cache.get(self.message_id, 0))
        if resp is not None and self.edited_timestamp:
            if (
                (
                    resp.embeds
                    and (image := resp.embeds[0].image)
                    and f"/attachments/{self.channel_id}/" in image.url
                )
                or resp.attachments
                or attachment
                or attachments
            ):
                await resp.delete()

            else:
                if current_paginator := self.bot._paginators.get(resp.id):
                    await current_paginator.stop(not current_paginator == paginator)

                return await resp.edit(
                    content=content,
                    embed=embed,
                    mentions_everyone=mentions_everyone,
                    user_mentions=user_mentions,
                    role_mentions=role_mentions,
                )

        elif resp is None:
            self.bot._resp_cache.pop(self.message_id, None)

        resp = await super().respond(
            content=content,
            tts=tts,
            embed=embed,
            attachment=attachment,
            attachments=attachments,
            nonce=nonce,
            mentions_everyone=mentions_everyone,
            user_mentions=user_mentions,
            role_mentions=role_mentions,
        )

        if not (attachment or attachments):
            self.bot._resp_cache[self.message_id] = resp.id

        return resp

    @property
    def me(self) -> typing.Optional[hikari.Member]:
        return (
            self.guild_id
            and self.bot.me
            and self.bot.cache.get_member(self.guild_id, self.bot.me.id)
        )

    def execute_plugins(
        self, func: typing.Callable[[str], None], plugins: str
    ) -> typing.Awaitable[hikari.Message]:
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
            except Exception as e:
                self.bot.log.error("Failed to reload %s", plugin, exc_info=e)
                failed.add((plugin, e.__class__.__name__))

        loaded = "\n".join(f"+ {i}" for i in plugins_set ^ {x[0] for x in failed})
        failed = "\n".join(f"- {c} {e}" for c, e in failed)
        return self.respond(f"```diff\n{loaded}\n{failed}```")
