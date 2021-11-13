from __future__ import annotations

import typing
import weakref

from hikari import ActivityType, guilds, messages, presences, snowflakes, users
from hikari.impl.cache import CacheImpl
from hikari.internal import cache
from lightbulb import utils

from nokari.utils import converters

if typing.TYPE_CHECKING:
    from nokari.core.bot import Nokari

__all__: typing.Final[typing.List[str]] = ["Cache"]


class Cache(CacheImpl):
    _app: Nokari

    # Just a way to get users' Spotify presences
    _presences_garbage: typing.ClassVar[
        typing.MutableMapping[
            snowflakes.Snowflake, weakref.WeakSet[cache.MemberPresenceData]
        ]
    ] = {}

    def add_ref(
        self, user_id: snowflakes.Snowflake, presence: cache.MemberPresenceData
    ) -> None:
        # dunno if this is atomic, w/e
        try:
            self._presences_garbage[user_id].add(presence)
        except KeyError:
            self._presences_garbage[user_id] = weakref.WeakSet((presence,))

    def _gc(self, user_id: snowflakes.Snowflake) -> None:
        if not self._presences_garbage.get(user_id):
            self._presences_garbage.pop(user_id, None)

    def set_presence(self, presence: presences.MemberPresence, /) -> None:
        if (
            spotify := utils.get(
                presence.activities, name="Spotify", type=ActivityType.LISTENING
            )
        ) is None:
            self.delete_presence(presence.guild_id, presence.user_id)
            return None

        presence.activities = [spotify]

        super().set_presence(presence)

        if presences_ := self._guild_entries[presence.guild_id].presences:
            self.add_ref(
                presence.user_id,
                presences_[presence.user_id],
            )

        return None

    def delete_presence(
        self,
        guild: snowflakes.SnowflakeishOr[guilds.PartialGuild],
        user: snowflakes.SnowflakeishOr[users.PartialUser],
        /,
    ) -> typing.Optional[presences.MemberPresence]:
        try:
            return super().delete_presence(guild, user)
        finally:
            self._gc(snowflakes.Snowflake(user))

    def update_member(
        self, member: guilds.Member, /
    ) -> typing.Tuple[typing.Optional[guilds.Member], typing.Optional[guilds.Member]]:
        key = f"{member.guild_id}:{member.id}"
        if key in converters._member_cache:
            converters._member_cache[key] = member

        return super().update_member(member)

    def _garbage_collect_member(
        self,
        guild_record: cache.GuildRecord,
        member: cache.RefCell[cache.MemberData],
        *,
        decrement: typing.Optional[int] = None,
        deleting: bool = False,
    ) -> typing.Optional[cache.RefCell[cache.MemberData]]:
        try:
            return super()._garbage_collect_member(
                guild_record, member, decrement=decrement, deleting=deleting
            )
        finally:
            self._gc(snowflakes.Snowflake(member.object.user.object))

    def delete_member(
        self,
        guild: snowflakes.SnowflakeishOr[guilds.PartialGuild],
        user: snowflakes.SnowflakeishOr[users.PartialUser],
        /,
    ) -> typing.Optional[guilds.Member]:
        converters._member_cache.pop(
            f"{snowflakes.Snowflake(guild)}:{snowflakes.Snowflake(user)}", None
        )

        return super().delete_member(guild, user)

    def _set_member(
        self, member: guilds.Member, /, *, is_reference: bool = True
    ) -> cache.RefCell[cache.MemberData]:
        # not sure if returning None would break something, but w/e
        if (me := self._app.get_me()) is None or me.id != member.id:
            return None  # type: ignore

        return super()._set_member(member, is_reference=is_reference)

    def _garbage_collect_message(
        self,
        message: cache.RefCell[cache.MessageData],
        *,
        decrement: typing.Optional[int] = 1,
        override_ref: bool = False,
    ) -> typing.Optional[cache.RefCell[cache.MessageData]]:
        return super()._garbage_collect_message(
            message, decrement=decrement, override_ref=override_ref
        )

    def _on_message_expire(self, message: cache.RefCell[cache.MessageData], /) -> None:
        if not self._garbage_collect_message(message):
            self._referenced_messages[message.object.id] = message
            return

        self._app.responses_cache.pop(message.object.id, None)

    def clear_messages(self) -> cache.CacheView[snowflakes.Snowflake, messages.Message]:
        self._app.responses_cache.clear()
        return super().clear_messages()
