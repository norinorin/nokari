from __future__ import annotations

import typing

from hikari.impl.entity_factory import EntityFactoryImpl
from hikari.internal import data_binding
from hikari import snowflakes, presences, undefined, Snowflake
from lightbulb.utils import find

if typing.TYPE_CHECKING:
    from nokari.core.bot import Nokari


class EntityFactory(EntityFactoryImpl):
    _app: Nokari

    def deserialize_member_presence(
        self,
        payload: data_binding.JSONObject,
        *,
        guild_id: undefined.UndefinedOr[snowflakes.Snowflake] = undefined.UNDEFINED,
    ) -> presences.MemberPresence:
        if spotify := find(
            payload["activities"],
            lambda x: x.get("name") == "Spotify" and "sync_id" in x,
        ):
            self._app._sync_ids[Snowflake(payload["user"]["id"])] = spotify["sync_id"]

        return super().deserialize_member_presence(payload, guild_id=guild_id)
