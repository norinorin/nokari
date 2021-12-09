from __future__ import annotations

import typing
import weakref

from hikari import ActivityType, guilds, presences, snowflakes, users
from hikari.api import cache
from hikari.impl.cache import CacheImpl
from hikari.internal import cache as cache_util

from kita.utils import get

if typing.TYPE_CHECKING:
    from nokari.core.bot import Nokari

__all__ = ("Cache",)


class Cache(CacheImpl):
    _app: Nokari

    # Just a way to get users' Spotify presences
    _presences_garbage: typing.ClassVar[
        typing.MutableMapping[
            snowflakes.Snowflake, weakref.WeakSet[cache_util.MemberPresenceData]
        ]
    ] = {}

    def _add_presence_ref(
        self, user_id: snowflakes.Snowflake, presence: cache_util.MemberPresenceData
    ) -> None:
        # dunno if this is atomic, w/e
        try:
            self._presences_garbage[user_id].add(presence)
        except KeyError:
            self._presences_garbage[user_id] = weakref.WeakSet((presence,))

    def clear_presences(
        self,
    ) -> cache.CacheView[
        snowflakes.Snowflake,
        cache.CacheView[snowflakes.Snowflake, presences.MemberPresence],
    ]:
        self._presences_garbage.clear()
        return super().clear_presences()

    def _garbage_collect_presence(self, user_id: snowflakes.Snowflake) -> None:
        if not self._presences_garbage.get(user_id):
            self._presences_garbage.pop(user_id, None)

    def set_presence(self, presence: presences.MemberPresence, /) -> None:
        if (
            spotify := get(
                presence.activities, name="Spotify", type=ActivityType.LISTENING
            )
        ) is None:
            self.delete_presence(presence.guild_id, presence.user_id)
            return None

        presence.activities = [spotify]

        super().set_presence(presence)

        if presences_ := self._guild_entries[presence.guild_id].presences:
            self._add_presence_ref(
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
            self._garbage_collect_presence(snowflakes.Snowflake(user))

    def _garbage_collect_member(
        self,
        guild_record: cache_util.GuildRecord,
        member: cache_util.RefCell[cache_util.MemberData],
        *,
        decrement: typing.Optional[int] = None,
        deleting: bool = False,
    ) -> typing.Optional[cache_util.RefCell[cache_util.MemberData]]:
        try:
            return super()._garbage_collect_member(
                guild_record, member, decrement=decrement, deleting=deleting
            )
        finally:
            self._garbage_collect_presence(
                snowflakes.Snowflake(member.object.user.object)
            )

    def _set_member(
        self, member: guilds.Member, /, *, is_reference: bool = True
    ) -> cache_util.RefCell[cache_util.MemberData]:
        # not sure if returning None would break something, but w/e
        if (me := self._app.get_me()) is None or me.id != member.id:
            return None  # type: ignore

        return super()._set_member(member, is_reference=is_reference)

    def _garbage_collect_message(
        self,
        message: cache_util.RefCell[cache_util.MessageData],
        *,
        decrement: typing.Optional[int] = None,
        override_ref: bool = False,
    ) -> typing.Optional[cache_util.RefCell[cache_util.MessageData]]:
        if decrement is not None:
            self._increment_ref_count(message, -decrement)

        if not self._can_remove_message(message) or override_ref:
            return None

        self._garbage_collect_user(message.object.author, decrement=1)

        if message.object.member:
            guild_record = self._guild_entries.get(
                message.object.member.object.guild_id
            )
            if guild_record:
                self._garbage_collect_member(
                    guild_record, message.object.member, decrement=1
                )

        if (
            not (referenced_message := message.object.referenced_message)
            and (message_reference := message.object.message_reference)
            and (msg_id := message_reference.id)
        ):
            referenced_message = self._message_entries.get(
                msg_id
            ) or self._referenced_messages.get(msg_id)

        if referenced_message:
            self._garbage_collect_message(referenced_message, decrement=1)

        if message.object.mentions.users:
            for user in message.object.mentions.users.values():
                self._garbage_collect_user(user, decrement=1)

        # If we got this far the message won't be in _message_entries as that'd infer that it hasn't been marked as
        # deleted yet.
        if message.object.id in self._referenced_messages:
            del self._referenced_messages[message.object.id]

        return message
