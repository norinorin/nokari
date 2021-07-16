from __future__ import annotations

import datetime
import re
import typing
from dataclasses import dataclass

import hikari
import pytz

from nokari.utils import get_luminance

if typing.TYPE_CHECKING:
    from . import SpotifyClient

_RGB = typing.Tuple[int, ...]
T = typing.TypeVar("T", bound="BaseSpotify")


class _SpotifyCardMetadata(typing.TypedDict):
    font_color: _RGB
    alt_color: _RGB
    height: int
    timestamp: typing.Tuple[str, str, float]


@dataclass()
class SongMetadata:
    timestamp: typing.Optional[typing.Tuple[str, str, float]]
    album_cover_url: str
    artists: str
    title: str
    album: str


class SpotifyCodeable:
    uri: str

    def get_code_url(self, color: hikari.Color) -> str:
        font_color = "white" if get_luminance(color.rgb) < 128 else "black"
        return f"https://scannables.scdn.co/uri/plain/png/{color.raw_hex_code}/{font_color}/640/{self.uri}"


class _CamelotType(type):
    def __getitem__(cls, item: typing.Tuple[int, int]) -> str:
        key, mode = item
        return f"{((8 if mode else 5) + 7 * key) % 12 or 12}{'B' if mode else 'A'}"


class Camelot(metaclass=_CamelotType):
    """The actual Camelot class."""


@dataclass()
class BaseSpotify:
    client: SpotifyClient
    id: str
    uri: str
    type: typing.ClassVar[str] = "base"

    @classmethod
    def from_dict(
        cls: typing.Type[T],
        client: SpotifyClient,
        payload: typing.Dict[str, typing.Any],
    ) -> T:
        merged_annotations = {
            **cls.__annotations__,
            **{
                k: v
                for parent in cls.__mro__
                if hasattr(parent, "__annotations__")
                for k, v in parent.__annotations__.items()
            },
        }

        kwargs = convert_data(
            client,
            {k: v for k, v in payload.items() if k in merged_annotations},
        )

        if "url" in merged_annotations:
            kwargs["url"] = payload["external_urls"]["spotify"]

        if "cover_url" in merged_annotations and "images" in payload:
            kwargs["cover_url"] = (
                images[0]["url"] if (images := payload["images"]) else ""
            )

        if "follower_count" in merged_annotations and "followers" in payload:
            kwargs["follower_count"] = payload["followers"]["total"]

        kwargs.pop("type", None)

        return cls(client, **kwargs)

    def __str__(self) -> str:
        return getattr(self, "name", super().__str__())

    @property
    def formatted_url(self) -> str:
        if not hasattr(self, "url") or not hasattr(self, "name"):
            raise NotImplementedError

        return f"[{self}]({getattr(self, 'url')} '{self} on Spotify')"


class ArtistAware:
    artists: typing.Sequence[PartialArtist]

    @property
    def artists_str(self) -> str:
        return ", ".join(map(str, self.artists))


# pylint: disable=too-many-instance-attributes
@dataclass()
class AudioFeatures(BaseSpotify):
    keys: typing.ClassVar[typing.List[str]] = [
        "C",
        "D♭",
        "D",
        "E♭",
        "E",
        "F",
        "F#",
        "G",
        "A♭",
        "A",
        "B♭",
        "B",
    ]
    modes: typing.ClassVar[typing.List[str]] = ["Minor", "Major"]
    danceability: float
    energy: float
    key: int
    loudness: float
    mode: int
    speechiness: float
    acousticness: float
    instrumentalness: float
    liveness: float
    valence: float
    tempo: float
    analysis_url: str
    duration_ms: int
    time_signature: int
    type: typing.ClassVar[typing.Literal["audio_features"]] = "audio_features"

    def get_key(self) -> str:
        return f"{self.keys[self.key]} {self.modes[self.mode]}"

    def get_camelot(self) -> str:
        return Camelot[self.key, self.mode]


@dataclass()
class PartialTrack(BaseSpotify, ArtistAware, SpotifyCodeable):
    name: str
    artists: typing.List[PartialArtist]
    url: str
    disc_number: int
    track_number: int
    type: typing.ClassVar[typing.Literal["track"]] = "track"

    @property
    def title(self) -> str:
        return self.name

    def get_formatted_url(self, prepend_artists: bool = True) -> str:
        if not prepend_artists:
            return self.formatted_url

        return f"[{self.artists_str} - {self}]({self.url} '{self} on Spotify')"

    def get_audio_features(
        self,
    ) -> typing.Coroutine[typing.Any, typing.Any, AudioFeatures]:
        return self.client.get_audio_features(self.id)


@dataclass()
class Track(PartialTrack):
    album: PartialAlbum
    popularity: int
    duration_ms: int

    @property
    def album_cover_url(self) -> str:
        return self.album.cover_url if self.album else ""


@dataclass()
class PartialArtist(BaseSpotify, SpotifyCodeable):
    name: str
    url: str
    type: typing.ClassVar[typing.Literal["artist"]] = "artist"

    def get_top_tracks(
        self, country: str = "US"
    ) -> typing.Coroutine[typing.Any, typing.Any, typing.List[Track]]:
        return self.client.get_top_tracks(self.id, country)


@dataclass()
class Artist(PartialArtist):
    popularity: int
    genres: typing.List[str]
    follower_count: int
    cover_url: str = ""


@dataclass()
class PartialAlbum(BaseSpotify, ArtistAware, SpotifyCodeable):
    album_type: typing.Literal["album", "single"]
    artists: typing.List[PartialArtist]
    name: str
    cover_url: str
    url: str
    release_date: datetime.datetime
    type: typing.ClassVar[typing.Literal["album"]] = "album"


@dataclass()
class Album(PartialAlbum):
    popularity: int
    total_tracks: int
    label: str
    copyrights: Copyrights
    genres: typing.List[str]
    tracks: typing.List[PartialTrack]

    @property
    def copyright(self) -> typing.Optional[str]:
        return self.copyrights.get("Copyright")

    @property
    def phonogram(self) -> typing.Optional[str]:
        return self.copyrights.get("Phonogram")


class Copyrights(typing.TypedDict, total=False):
    Copyright: str
    Phonogram: str


class Spotify:
    def __init__(self, act: hikari.RichActivity) -> None:
        self._act = act

    @property
    def album_cover_url(self) -> str:
        return (self._act.assets and self._act.assets.large_image or "").replace(
            "spotify:", "https://i.scdn.co/image/"
        )

    @property
    def title(self) -> str:
        return self._act.details or ""

    # pylint: disable=consider-using-ternary
    @property
    def album(self) -> str:
        return (self._act.assets and self._act.assets.large_text) or "Local Files"

    @property
    def artists(self) -> str:
        return (self._act.state or "").replace("; ", ", ")

    @property
    def timestamps(self) -> typing.Optional[hikari.ActivityTimestamps]:
        return self._act.timestamps


SPOTIFY_DATE = re.compile(r"(?P<Y>\d{4})(?:-(?P<m>\d{2})-(?P<d>\d{2}))?")


def convert_data(
    client: SpotifyClient, d: typing.Dict[str, typing.Any]
) -> typing.Dict[str, typing.Any]:
    for k, v in d.items():
        if k == "artists":
            d["artists"] = [
                PartialArtist.from_dict(client, artist) for artist in d["artists"]
            ]

        elif k == "album":
            d["album"] = PartialAlbum.from_dict(client, d["album"])

        elif k == "release_date":
            # we couldn't really rely on "release_date_precision"
            # since it's optional, so we're just gonna check it on our own
            match = SPOTIFY_DATE.match(v)

            if not match:
                raise RuntimeError(f"Unable to parse {k}: {v}")

            pattern = "-".join([f"%{k}" for k, v in match.groupdict().items() if v])

            d["release_date"] = datetime.datetime.strptime(v, pattern).replace(
                tzinfo=pytz.UTC
            )

        elif k == "copyrights":
            # YIIIKKKKEEESSS
            mapping = {
                "C": ("Copyright", "\N{COPYRIGHT SIGN} "),
                "P": ("Phonogram", "\N{SOUND RECORDING COPYRIGHT} "),
            }
            d[k] = {
                cp[0]: cp[1]
                + c["text"].replace(f"({_type})", "").replace(cp[1], "").strip()
                for c in v
                if (_type := c["type"]) and (cp := mapping[_type])
            }

        elif k == "tracks":
            d[k] = [
                PartialTrack.from_dict(client, track) for track in d["tracks"]["items"]
            ]

        elif isinstance(v, dict):
            d[k] = convert_data(client, d[k])

    return d
