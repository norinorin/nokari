import asyncio
import typing
from functools import partial

import spotipy

from nokari.utils.spotify.typings import Playlist


class SpotifyRest:
    def __init__(
        self,
        *,
        executor: typing.Any = None,
    ) -> None:
        self.spotipy = spotipy.Spotify(auth_manager=spotipy.SpotifyClientCredentials())
        self._loop = asyncio.get_running_loop()
        self._executor = executor

    def __getattr__(self, attr: str) -> partial[typing.Awaitable[typing.Any]]:
        return partial(
            self._loop.run_in_executor, self._executor, getattr(self.spotipy, attr)
        )

    # pylint: disable=redefined-builtin
    async def album(self, album_id: str) -> typing.Dict[str, typing.Any]:
        res = await self.__getattr__("album")(album_id)
        next = res["tracks"]["next"]

        while next:
            ext = await self.__getattr__("_get")(next)
            res["tracks"]["items"].extend(ext["items"])
            next = ext["next"]

        return res

    async def playlist(self, playlist_id: str) -> typing.Dict[str, typing.Any]:
        res = await self.__getattr__("playlist")(playlist_id)
        next = res["tracks"]["next"]

        while next:
            ext = await self.__getattr__("_get")(next)
            res["tracks"]["items"].extend(ext["items"])
            next = ext["next"]

        res["total_tracks"] = len(res["tracks"]["items"])
        return res
