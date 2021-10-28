import json
import time
import typing

import aiohttp

CACHE_FILE_NAME = ".spat"


class Credentials:
    def __init__(self):
        self.token = None
        self.expires_at = None

        try:
            with open(CACHE_FILE_NAME, "r") as f:
                cache = json.load(f)
        except FileNotFoundError:
            pass
        else:
            self._set_prop(cache)

    async def get_access_token(self) -> str:
        if self.expires_at and time.time() < self.expires_at:
            return self.token

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://open.spotify.com/get_access_token",
                headers={"User-Agent": "Nokari Bot"},
            ) as r:
                data = await r.json()
                with open(CACHE_FILE_NAME, "w") as f:
                    json.dump(data, f)

                self._set_prop(data)

        return self.token

    def _set_prop(self, data: typing.Dict[str, typing.Any]) -> None:
        self.token = "Bearer " + data["accessToken"]
        self.expires_at = data["accessTokenExpirationTimestampMs"] / 1000
