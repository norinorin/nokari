import typing

from hikari import ActivityType, guilds, presences, snowflakes, users
from hikari.impl.cache import CacheImpl
from hikari.internal import cache
from lightbulb import utils

from nokari.utils import converters

__all__: typing.Final[typing.List[str]] = ["Cache"]


class Cache(CacheImpl):
    def set_presence(self, presence: presences.MemberPresence, /) -> None:
        if (
            spotify := utils.get(
                presence.activities, name="Spotify", type=ActivityType.LISTENING
            )
        ) is None:
            return None

        presence.activities = [spotify]

        return super().set_presence(presence)

    def update_member(
        self, member: guilds.Member, /
    ) -> typing.Tuple[typing.Optional[guilds.Member], typing.Optional[guilds.Member]]:
        key = f"{member.guild_id}:{member.id}"
        if key in converters._member_cache:
            converters._member_cache[key] = member

        return super().update_member(member)

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
        if (me := self._app.me) is None or me.id != member.id:
            return None  # type: ignore

        return super()._set_member(member, is_reference=is_reference)
