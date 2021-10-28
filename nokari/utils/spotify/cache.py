from __future__ import annotations

import asyncio
import typing

from lru import LRU  # pylint: disable=no-name-in-module

if typing.TYPE_CHECKING:
    from .typings import BaseSpotify, T


class SpotifyCache:
    # pylint: disable=too-many-instance-attributes
    def __init__(self) -> None:
        self._tracks = LRU(50)
        self._artists = LRU(50)
        self._audio_features = LRU(50)
        self._top_tracks = LRU(50)
        self._user_playlists = LRU(50)
        self._albums = LRU(50)
        self._users = LRU(50)
        self._playlists = LRU(50)
        self._queries: typing.Dict[str, LRU] = {
            i: LRU(50) for i in ("artist", "track", "album", "playlist")
        }
        self._task: asyncio.Task[None] = asyncio.create_task(self.start_clear_loop())

    def __del__(self) -> None:
        self._task.cancel()

    # pylint: disable=redefined-builtin
    def get_container(self, type: str) -> LRU:
        return getattr(self, f"{type}{'s'*(not type.endswith('s'))}")

    def update_items(self, items: typing.Sequence[BaseSpotify]) -> None:
        if not items:
            return

        self.get_container(items[0].type).update(
            {
                item.id: item
                for item in items
                if not item.__class__.__name__.startswith("Partial")
            }
        )

    def set_item(self, item: T) -> T:
        if item.__class__.__name__.startswith("Partial"):
            return item

        self.get_container(item.type)[item.id] = item
        return item

    @property
    def albums(self) -> LRU:
        return self._albums

    @property
    def tracks(self) -> LRU:
        return self._tracks

    @property
    def artists(self) -> LRU:
        return self._artists

    @property
    def audio_features(self) -> LRU:
        return self._audio_features

    @property
    def top_tracks(self) -> LRU:
        return self._top_tracks

    @property
    def user_playlists(self) -> LRU:
        return self._user_playlists

    @property
    def users(self) -> LRU:
        return self._users

    @property
    def playlists(self) -> LRU:
        return self._playlists

    @property
    def queries(self) -> typing.Dict[str, LRU]:
        return self._queries

    def get_queries(self, type_name: str) -> LRU:
        return self._queries[type_name]

    async def start_clear_loop(self) -> None:
        while 1:
            await asyncio.sleep(86400)
            self._tracks.clear()
            self._artists.clear()
            self._audio_features.clear()
            self._top_tracks.clear()
            self._albums.clear()
            _ = [i.clear() for i in self._queries.values()]
