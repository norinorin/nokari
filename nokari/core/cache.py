from hikari import ActivityType, guilds, presences
from hikari.impl.cache import CacheImpl
from hikari.internal import cache
from lightbulb import utils


class Cache(CacheImpl):
    def set_presence(self, presence: presences.MemberPresence, /) -> None:
        if (
            spotify := utils.find(
                presence.activities,
                lambda x: x.name
                and x.name == "Spotify"
                and x.type is ActivityType.LISTENING,
            )
        ) is None:
            return None

        presence.activities = [spotify]

        return super().set_presence(presence)

    def _set_member(
        self, member: guilds.Member, /, *, is_reference: bool = True
    ) -> cache.RefCell[cache.MemberData]:
        if (me := self._app.me) is None or me.id != member.id:
            return None  # type: ignore

        return super()._set_member(member, is_reference=is_reference)
