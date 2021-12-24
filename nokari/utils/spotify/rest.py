from __future__ import annotations

import asyncio
import json
import typing
from functools import partial

import aiohttp
import spotipy

from nokari.utils.spotify.credentials import Credentials

if typing.TYPE_CHECKING:
    from nokari.utils.spotify.typings import ArtistOverview

EXTENSIONS: typing.Final[str] = json.dumps(
    {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "c54d1f5a13f7780be8ad8df47e076f811abea3c682c57221cd04d1bc59a65e07",
        }
    }
)


class SpotifyRest:
    def __init__(
        self,
        *,
        executor: typing.Any = None,
    ) -> None:
        self.spotipy = spotipy.Spotify(auth_manager=spotipy.SpotifyClientCredentials())
        self.api_partner_credentials = Credentials()
        self._loop = asyncio.get_running_loop()
        self._executor = executor
        self._session = aiohttp.ClientSession()

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

    async def artist_overview(self, artist_id: str) -> ArtistOverview:
        async with self._session.get(
            "https://api-partner.spotify.com/pathfinder/v1/query?",
            headers={
                "Authorization": await self.api_partner_credentials.get_access_token()
            },
            params={
                "operationName": "queryArtistOverview",
                "variables": json.dumps({"uri": f"spotify:artist:{artist_id}"}),
                "extensions": EXTENSIONS,
            },
        ) as r:
            res = await r.json()

        artist = res["data"]["artist"]
        stats = artist["stats"]
        return {
            "verified": artist["profile"]["verified"],
            "top_tracks": [
                (i["track"]["name"], i["track"]["playcount"])
                for i in artist["discography"]["topTracks"]["items"]
            ],
            "monthly_listeners": stats["monthlyListeners"],
            "follower_count": stats["followers"],
            "top_cities": [
                (i["city"] + ", " + i["country"], i["numberOfListeners"])
                for i in stats["topCities"]["items"]
            ],
        }

    async def user_overview(self, user_id: str) -> typing.Dict[str, typing.Any]:
        raise NotImplementedError
