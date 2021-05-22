"""A module that contains a Spotify card generation implementation."""

from __future__ import annotations

import asyncio
import datetime
import re
import typing
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from io import BytesIO

import hikari
import numpy
import pytz
import spotipy
from colorthief import ColorThief
from fuzzywuzzy import fuzz
from lightbulb import Bot, utils
from lru import LRU  # pylint: disable=no-name-in-module
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import caches
from .algorithm import get_alt_color, get_luminance
from .formatter import get_timestamp as format_time
from .images import get_dominant_color, has_transparency, right_fade, round_corners

if typing.TYPE_CHECKING:
    from nokari.core import Context, Nokari

_RGB = typing.Tuple[int, ...]
_RGBs = typing.List[_RGB]
T = typing.TypeVar("T", bound="BaseSpotify")


class NoSpotifyPresenceError(Exception):
    """Raised when the member doesn't have Spotify presence"""


class LocalFilesDetected(Exception):
    """Raised when the member is listening to local files on Spotify"""


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
    """The actual Camelot class"""


SPOTIFY_URL = re.compile(
    r"(?:https?://)?open.spotify.com/(?:track|album|artist|playlist)/(?P<id>\w+)"
)
SPOTIFY_DATE = re.compile(r"(?P<Y>\d{4})(?:-(?P<m>\d{2})-(?P<d>\d{2}))?")


def convert_data(
    client: SpotifyClient, d: typing.Dict[str, typing.Any]
) -> typing.Dict[str, typing.Any]:
    for k, v in d.items():
        if k == "artists":
            d["artists"] = [Artist.from_dict(client, artist) for artist in d["artists"]]

        elif k == "album":
            d["album"] = Album.from_dict(client, d["album"])

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

        elif isinstance(v, dict):
            d[k] = convert_data(client, d[k])

    return d


# pylint: disable=redefined-builtin
def get_type_name(type: typing.Type) -> str:
    return type.__name__.lower()


@dataclass()
class BaseSpotify:
    client: SpotifyClient
    id: str
    type: str
    uri: str

    @classmethod
    def from_dict(
        cls: typing.Type[T],
        client: SpotifyClient,
        payload: typing.Dict[str, typing.Any],
    ) -> T:
        kwargs = convert_data(
            client,
            {
                k: v
                for k, v in payload.items()
                if k in {**cls.__annotations__, **BaseSpotify.__annotations__}
            },
        )

        if "url" in cls.__annotations__:
            kwargs["url"] = payload["external_urls"]["spotify"]

        if "cover_url" in cls.__annotations__ and "images" in payload:
            kwargs["cover_url"] = (
                images[0]["url"] if (images := payload["images"]) else ""
            )

        if "follower_count" in cls.__annotations__ and "followers" in payload:
            kwargs["follower_count"] = payload["followers"]["total"]

        return cls(client, **kwargs)

    def __str__(self) -> str:
        return getattr(self, "name", super().__str__())

    @property
    def formatted_url(self) -> str:
        if not hasattr(self, "url") or not hasattr(self, "name"):
            raise NotImplementedError

        return f"[{self}]({getattr(self, 'url')} '{self} on Spotify')"


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

    def get_key(self) -> str:
        return f"{self.keys[self.key]} {self.modes[self.mode]}"

    def get_camelot(self) -> str:
        return Camelot[self.key, self.mode]


@dataclass()
class Track(BaseSpotify, SpotifyCodeable):
    name: str
    artists: typing.List[Artist]
    album: Album
    popularity: int
    url: str
    track_number: int

    @property
    def album_cover_url(self) -> str:
        return self.album.cover_url

    @property
    def artists_str(self) -> str:
        return ", ".join(map(str, self.artists))

    @property
    def title(self) -> str:
        return self.name

    def get_audio_features(
        self,
    ) -> typing.Coroutine[typing.Any, typing.Any, AudioFeatures]:
        return self.client.get_audio_features(self.id)


@dataclass()
class Artist(BaseSpotify, SpotifyCodeable):
    name: str
    url: str
    cover_url: str = ""
    popularity: int = 0
    genres: typing.Optional[typing.List[str]] = None
    follower_count: int = 0

    def get_top_tracks(
        self, country: str = "US"
    ) -> typing.Coroutine[typing.Any, typing.Any, typing.List[Track]]:
        return self.client.get_top_tracks(self.id, country)


@dataclass()
class Album(BaseSpotify, SpotifyCodeable):
    album_type: typing.Literal["album", "single"]
    artists: typing.List[Artist]
    name: str
    cover_url: str
    url: str
    release_date: datetime.datetime


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


class SpotifyCache:
    def __init__(self) -> None:
        self._tracks = LRU(50)
        self._artists = LRU(50)
        self._audio_features = LRU(50)
        self._top_tracks = LRU(50)
        self._queries: typing.Dict[str, LRU] = {i: LRU(50) for i in ("artist", "track")}

    # pylint: disable=redefined-builtin
    def get_container(self, type: str) -> LRU:
        return getattr(self, f"{type}{'s'*(not type.endswith('s'))}")

    def update_items(self, items: typing.Sequence[BaseSpotify]) -> None:
        if not items:
            return

        self.get_container(items[0].type).update({item.id: item for item in items})

    def set_item(self, item: T) -> T:
        self.get_container(item.type)[item.id] = item
        return item

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
    def queries(self) -> typing.Dict[str, LRU]:
        return self._queries

    def get_queries(self, type_name: str) -> LRU:
        return self._queries[type_name]


class SpotifyRest:
    def __init__(
        self,
        *,
        loop: typing.Optional[asyncio.AbstractEventLoop] = None,
        executor: typing.Any = None,
    ) -> None:
        self.spotipy = spotipy.Spotify(auth_manager=spotipy.SpotifyClientCredentials())
        self._loop = loop or asyncio.get_event_loop()
        self._executor = executor

    def __getattr__(self, attr: str) -> partial[typing.Awaitable[typing.Any]]:
        return partial(
            self._loop.run_in_executor, self._executor, getattr(self.spotipy, attr)
        )


class SpotifyClient:
    """A class that generates Spotify cards as well as interacts with Spotify API"""

    SMALL_FONT = ImageFont.truetype("nokari/assets/fonts/arial-unicode-ms.ttf", size=40)
    BIG_FONT = ImageFont.truetype("nokari/assets/fonts/arial-unicode-ms.ttf", size=50)
    C1_BOLD_FONT = ImageFont.truetype(
        "nokari/assets/fonts/Arial-Unicode-Bold.ttf", size=100
    )
    C2_BOLD_FONT = ImageFont.truetype(
        "nokari/assets/fonts/Arial-Unicode-Bold.ttf", size=60
    )
    SIDE_GAP = 50
    WIDTH = 1280

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.loop = bot.loop
        self.cache = SpotifyCache()
        self.rest = SpotifyRest(loop=bot.loop)

    @staticmethod
    def _get_timestamp(spotify: Spotify) -> typing.Tuple[str, str, float]:
        """Gets the timestamp of the playing song"""

        if (
            (timestamps := spotify.timestamps) is None
            or timestamps.start is None
            or timestamps.end is None
        ):
            raise RuntimeError(
                "Missing timestamps, the object might not be a Spotify object."
            )

        elapsed = datetime.datetime.now(tz=datetime.timezone.utc) - timestamps.start
        duration = timestamps.end - timestamps.start

        prog = min(
            max(elapsed.total_seconds() / duration.total_seconds() * 100, 0), 100
        )

        dur: str = format_time(duration)
        pos: str = (
            dur
            if prog == 100
            else format_time(elapsed)
            if elapsed.total_seconds() > 0
            else "0:00"
        )

        return pos, dur, prog

    @staticmethod
    def _generate_rounded_rectangle(
        size: typing.Tuple[int, int], rad: int, fill: _RGB
    ) -> Image.Image:
        """Generates a rounded rectangle image"""

        rectangle = Image.new("RGBA", size, fill)
        round_corners(rectangle, rad)
        return rectangle

    @caches.cache(20)
    async def _get_album(self, album_url: str) -> bytes:
        if self.bot.session is None:
            raise RuntimeError("Missing ClientSession...")

        async with self.bot.session.get(album_url) as r:
            return await r.read()

    @caches.cache(20)
    async def _get_spotify_code(self, spotify_code_url: str) -> bytes:
        """
        Duplicates of _get_album as it isn't supposed to share the cache
        """
        if self.bot.session is None:
            raise RuntimeError("Missing ClientSession...")

        async with self.bot.session.get(spotify_code_url) as r:
            return await r.read()

    async def _get_album_and_colors(
        self, album_url: str, height: int, mode: str
    ) -> typing.Tuple[typing.Tuple[_RGB, _RGBs], Image.Image]:
        album = BytesIO(await self._get_album(album_url))
        return self._get_colors(album, mode, album_url), Image.open(album).convert(
            "RGBA"
        ).resize((height,) * 2)

    @caches.cache(20)
    @staticmethod
    def _get_colors(
        image: BytesIO,
        mode: str = "full",
        image_url: str = "",  # necessary for caching
    ) -> typing.Tuple[_RGB, _RGBs]:
        """Returns the dominant color as well as other colors present in the image"""

        def get_palette() -> _RGBs:
            color_thief = ColorThief(image)
            palette = color_thief.get_palette(color_count=5, quality=100)
            return palette

        def get_dom_color() -> typing.Optional[_RGB]:
            im = Image.open(image)
            if has_transparency(im) or mode == "colorthief":
                return None

            w, h = [i // 4 for i in im.size]
            im = im.resize((w, h))
            if "crop" in mode:
                im = im.crop((0, 0, w, h / 6))

            elif "downscale" in mode:
                im = im.resize((int(w / 2), int(h / 2)), resample=0)

            elif "left-right" in mode:
                div = w // 6
                back_im = Image.new("RGB", (div * 2, h), 0)
                left = im.crop((0, 0, div, h))
                right = im.crop((w - div, 0, w, h))
                back_im.paste(left, (0, 0))
                back_im.paste(right, (div, 0))
                im = back_im

            elif "top-bottom" in mode:
                div = h // 6
                back_im = Image.new("RGB", (w, div * 2), 0)
                top = im.crop((0, 0, w, div))
                bot = im.crop((0, h - div, w, h))
                back_im.paste(top, (0, 0))
                back_im.paste(bot, (0, div))
                im = back_im

            if "blur" in mode:
                im = im.filter(ImageFilter.GaussianBlur(2))

            dom_color = get_dominant_color(im)
            im.close()
            return dom_color

        dom_color, palette = get_dom_color(), get_palette()
        if dom_color is None and palette is not None:
            dom_color = palette.pop(0)

        return dom_color, palette

    code_cache = _get_spotify_code.cache  # type: ignore
    album_cache = _get_album.cache  # type: ignore
    color_cache = _get_colors.cache  # type: ignore

    @staticmethod
    def _get_char_size_map(
        text: str, draw: ImageDraw, font: ImageFont
    ) -> typing.Dict[str, typing.Tuple[int, int]]:
        return {char: draw.textsize(char, font=font) for char in set(text)}

    @staticmethod
    def _get_height_from_text(
        text: str,
        map_: typing.Dict[str, typing.Tuple[int, int]],
        threshold: typing.Union[int, float] = float("inf"),
    ) -> int:
        w = h = 0
        for char in text:
            if w >= threshold:
                break

            char_size = map_[char]

            w += char_size[0]

            if char_size[1] > h:
                h = char_size[1]

        return h

    # pylint: disable=too-many-arguments, too-many-locals
    async def _generate_base_card1(
        self,
        metadata: SongMetadata,
        hidden: bool,
        color_mode: str,
    ) -> typing.Tuple[Image.Image, typing.Optional[_SpotifyCardMetadata]]:
        metadata.album = f"on {metadata.album}"

        title_width = self.C1_BOLD_FONT.getsize(metadata.title)[0]

        album_cover_size = 300

        height = raw_height = album_cover_size + self.SIDE_GAP * 3

        if hidden:
            height -= self.SIDE_GAP

        rgbs, im = await self._get_album_and_colors(
            metadata.album_cover_url, height, color_mode or "downscale"
        )

        width = (
            width if (width := title_width + raw_height) > self.WIDTH else self.WIDTH
        )

        def wrapper(
            metadata: SongMetadata,
            rgbs: typing.Tuple[typing.Tuple[_RGB, _RGBs]],
            im: Image.Image,
        ) -> typing.Tuple[Image.Image, typing.Optional[_SpotifyCardMetadata]]:
            canvas = Image.new("RGB", (width, height), rgbs[0])

            round_corners(im, self.SIDE_GAP)

            im = im.resize((album_cover_size,) * 2)

            canvas.paste(im, (self.SIDE_GAP,) * 2, im)

            text_area = width - raw_height

            artist, album = [
                self._shorten_text(self.BIG_FONT, i, text_area)
                for i in (metadata.artists, metadata.album)
            ]

            font_color = self._get_font_color(*rgbs)  # type: ignore

            draw = ImageDraw.Draw(canvas)

            title_c_map = self._get_char_size_map(
                metadata.title, draw, self.C1_BOLD_FONT
            )
            artist_c_map = self._get_char_size_map(artist, draw, self.BIG_FONT)
            album_c_map = self._get_char_size_map(album, draw, self.BIG_FONT)

            threshold = min(
                [
                    sum([map_[c][0] for c in text])
                    for map_, text in (
                        (artist_c_map, artist),
                        (album_c_map, album),
                    )
                ]
                + [title_width]
            )

            title_h = self._get_height_from_text(metadata.title, title_c_map, threshold)
            artist_h = self._get_height_from_text(artist, artist_c_map, threshold)
            album_h = self._get_height_from_text(album, album_c_map, threshold)

            outer_gap = (album_cover_size - title_h - artist_h - album_h) // 4

            title_y = self.SIDE_GAP + outer_gap
            artist_y = title_y + title_h
            album_y = artist_y + artist_h

            draw.text(
                (raw_height - self.SIDE_GAP, title_y),
                metadata.title,
                font=self.C1_BOLD_FONT,
                fill=font_color,
            )

            draw.text(
                (raw_height - self.SIDE_GAP, artist_y),
                artist,
                font=self.BIG_FONT,
                fill=font_color,
            )

            draw.text(
                (raw_height - self.SIDE_GAP, album_y),
                album,
                font=self.BIG_FONT,
                fill=font_color,
            )

            round_corners(canvas, self.SIDE_GAP // 2)

            if hidden or metadata.timestamp is None:
                return canvas, None

            return canvas, _SpotifyCardMetadata(
                font_color=font_color,
                alt_color=get_alt_color(typing.cast(typing.Tuple[int, ...], rgbs[0])),
                height=raw_height,
                timestamp=metadata.timestamp,
            )

        return await self.loop.run_in_executor(
            self.bot.executor, wrapper, metadata, rgbs, im
        )

    # pylint: disable=too-many-arguments,too-many-locals,too-many-statements
    async def _generate_base_card2(
        self,
        metadata: SongMetadata,
        hidden: bool,
        color_mode: str,
    ) -> typing.Tuple[Image.Image, typing.Optional[_SpotifyCardMetadata]]:
        width = self.WIDTH

        height = raw_height = 425

        decrement = int(self.SIDE_GAP * 2.5)

        if hidden:
            width -= self.SIDE_GAP * 2
            height -= decrement

        rgbs, im = await self._get_album_and_colors(
            metadata.album_cover_url, height, color_mode or "top-bottom blur"
        )

        def wrapper(
            metadata: SongMetadata,
        ) -> typing.Tuple[Image.Image, typing.Optional[_SpotifyCardMetadata]]:
            canvas = Image.new("RGB", (width, height), rgbs[0])

            base_rad = width * 0.0609375

            delta = self.WIDTH - width

            canvas_fade = right_fade(
                canvas.crop((0, 0, height, height)),
                int(base_rad - (delta / self.SIDE_GAP / 2)),
            )

            canvas.paste(im, (width - height, 0), im)

            canvas.paste(canvas_fade, (width - height, 0), canvas_fade)

            text_area = width - height - self.SIDE_GAP * 2

            title, artist = [
                self._shorten_text(f, t, text_area)
                for f, t in (
                    (self.C2_BOLD_FONT, metadata.title),
                    (self.BIG_FONT, metadata.artists),
                )
            ]

            font_color = self._get_font_color(*rgbs)

            alt_color = [get_alt_color(font_color, i, rgbs[0]) for i in (20, 30)]

            alt_color.append(font_color)

            # cast to bool to suppress numpy deprecation warning.
            alt_color, lighter_color, font_color = sorted(
                alt_color, key=get_luminance, reverse=bool(get_luminance(rgbs[0]) > 128)
            )

            data = numpy.array(Image.open("nokari/assets/media/Spotify-50px.png"))

            non_transparent_areas = data.T[-1] > 0

            data[..., :-1][non_transparent_areas.T] = lighter_color

            spotify_logo = Image.fromarray(data)

            canvas.paste(spotify_logo, (self.SIDE_GAP,) * 2, spotify_logo)

            draw = ImageDraw.Draw(canvas)

            spotify_text = "Spotify \u2022"

            spotify_album_c_mapping = self._get_char_size_map(
                spotify_text + metadata.album, draw, font=self.SMALL_FONT
            )

            spotify_width = sum(
                [spotify_album_c_mapping[char][0] for char in spotify_text]
            )

            album_x = decrement + spotify_width + spotify_album_c_mapping[" "][0]

            if metadata.album != "Local Files":
                album = self._shorten_text(
                    self.SMALL_FONT,
                    f"{metadata.album}",
                    text_area - album_x - decrement + self.SIDE_GAP * 3,
                )

            draw.text(
                (decrement, self.SIDE_GAP),
                spotify_text,
                font=self.SMALL_FONT,
                fill=lighter_color,
            )
            draw.text(
                (
                    album_x,
                    self.SIDE_GAP,
                ),
                album,
                font=self.SMALL_FONT,
                fill=alt_color,
            )

            title_h = draw.textsize(title, font=self.C2_BOLD_FONT)[1]
            artist_h = draw.textsize(artist, font=self.BIG_FONT)[1]

            outer_gap = (
                raw_height
                - decrement
                - title_h
                - artist_h
                - self.SIDE_GAP * 2
                - max([i[1] for i in spotify_album_c_mapping.values()])
            ) // 4

            title_y = self.SIDE_GAP * 2 + outer_gap
            artist_y = title_y + title_h + outer_gap

            draw.text(
                (self.SIDE_GAP, title_y), title, font=self.C2_BOLD_FONT, fill=font_color
            )
            draw.text(
                (self.SIDE_GAP, artist_y), artist, font=self.BIG_FONT, fill=alt_color
            )

            base_y = self.SIDE_GAP + self.SIDE_GAP // 2
            inc = self.SIDE_GAP // 10
            y1 = max_ = base_y + inc
            y2 = min_ = base_y - inc

            if hidden:
                y1, y2 = y2, y1

            draw.line(
                ((width - (max_ * 2 - min_), y1), (width - max_ + 1, y2)),
                fill=lighter_color,
                width=inc,
            )
            draw.line(
                ((width - max_ - 1, y2), (width - min_, y1)),
                fill=lighter_color,
                width=inc,
            )

            round_corners(canvas, self.SIDE_GAP)

            if hidden or metadata.timestamp is None:
                return canvas, None

            return canvas, _SpotifyCardMetadata(
                font_color=font_color,
                alt_color=lighter_color,
                height=raw_height,
                timestamp=metadata.timestamp,
            )

        return await self.loop.run_in_executor(self.bot.executor, wrapper, metadata)

    @caches.cache(100)
    @staticmethod
    def _shorten_text(font: ImageFont, text: str, threshold: int) -> str:
        width, _ = font.getsize(text)
        dot, _ = font.getsize("...")
        if width < threshold:
            return text

        while width + dot > threshold:
            text = text[:-1]
            width = font.getsize(text)[0]

        return text + "..."

    text_cache = _shorten_text.cache  # type: ignore

    def _get_data(self, data: typing.Union[hikari.Member, Track]) -> SongMetadata:
        timestamp = None

        if isinstance(data, hikari.Member):
            spotify = self._get_spotify_act(data)
            artists, title, album = spotify.artists, spotify.title, spotify.album
            timestamp = self._get_timestamp(spotify)
            album_cover_url = (
                spotify.album_cover_url
                or (data.avatar_url or data.default_avatar_url).url
            )
        else:
            album_cover_url, artists, title, album = (
                data.album_cover_url,
                data.artists_str,
                data.title,
                data.album.name,
            )

        return SongMetadata(timestamp, album_cover_url, artists, title, album)

    async def generate_spotify_card(
        self,
        buffer: BytesIO,
        data: typing.Union[hikari.Member, Track],
        hidden: bool,
        color_mode: str,
        style: str = "2",
    ) -> None:
        func = f"_generate_base_card{style}"
        metadata = self._get_data(data)
        canvas, card_data = await getattr(self, func)(metadata, hidden, color_mode)

        if card_data is not None:

            def wrapper() -> Image.Image:
                draw = ImageDraw.Draw(canvas)
                width = canvas.size[0]
                font_color, alt_color, height, timestamp = (
                    card_data["font_color"],
                    card_data["alt_color"],
                    card_data["height"],
                    card_data["timestamp"],
                )
                text_gap = 10
                if style == "1":
                    y = height - self.SIDE_GAP // 2

                    rectangle_length = timestamp[2] / 100 * width

                    coord = [(0, y), (rectangle_length, height)]
                    draw.rectangle(coord, fill=font_color)

                    coord = [(rectangle_length, y), (width, height)]
                    draw.rectangle(coord, fill=alt_color)

                    w, h = draw.textsize(timestamp[1], font=self.SMALL_FONT)

                    y -= text_gap + h

                    draw.text(
                        (text_gap, y),
                        timestamp[0],
                        font=self.SMALL_FONT,
                        fill=font_color,
                    )

                    draw.text(
                        (width - w - text_gap, y),
                        timestamp[1],
                        font=self.SMALL_FONT,
                        fill=font_color,
                    )
                else:
                    rectangle_length = timestamp[2] / 100 * (width - 100)
                    elapsed_bar = self._generate_rounded_rectangle(
                        (width - self.SIDE_GAP * 2, text_gap),
                        self.SIDE_GAP // 10,
                        (*alt_color, 255),
                    ).crop((0, 0, int(rectangle_length), 10))
                    total_bar = self._generate_rounded_rectangle(
                        (width - self.SIDE_GAP * 2, text_gap),
                        self.SIDE_GAP // 10,
                        (*alt_color, 150),
                    )

                    # pylint: disable=blacklisted-name
                    for bar in (total_bar, elapsed_bar):
                        canvas.paste(
                            bar,
                            (
                                self.SIDE_GAP,
                                height - self.SIDE_GAP * 2 - self.SIDE_GAP // 2,
                            ),
                            bar,
                        )

                    r = int(self.SIDE_GAP * 0.3)
                    x = rectangle_length + self.SIDE_GAP
                    y = height - r - self.SIDE_GAP * 2 - self.SIDE_GAP // 10
                    top_left = (x - r, y - r)
                    bot_right = (x + r, y + r)
                    draw.ellipse((top_left, bot_right), fill=font_color)

                    draw.text(
                        (self.SIDE_GAP, height - self.SIDE_GAP * 2),
                        timestamp[0],
                        font=self.SMALL_FONT,
                        fill=alt_color,
                    )
                    w, _ = draw.textsize(timestamp[1], font=self.SMALL_FONT)
                    draw.text(
                        (width - w - self.SIDE_GAP, height - self.SIDE_GAP * 2),
                        timestamp[1],
                        font=self.SMALL_FONT,
                        fill=alt_color,
                    )

                return canvas

            canvas = await self.loop.run_in_executor(self.bot.executor, wrapper)

        def save() -> None:
            canvas.save(buffer, "PNG")
            buffer.seek(0)

        await self.loop.run_in_executor(self.bot.executor, save)

    __call__ = generate_spotify_card

    @staticmethod
    def _get_spotify_act(member: hikari.Member) -> Spotify:
        exc = NoSpotifyPresenceError("The member has no Spotify presences")
        if not member.presence or not member.presence.activities:
            raise exc

        act = utils.find(
            member.presence.activities,
            lambda x: x.name
            and x.name == "Spotify"
            and x.type is hikari.ActivityType.LISTENING,
        )

        if act is None:
            raise exc

        return Spotify(act)

    @staticmethod
    def _get_font_color(
        base: typing.Sequence[int], seq: typing.Sequence[typing.Sequence[int]]
    ) -> typing.Tuple[int, ...]:
        """Gets the font color"""
        base_y = get_luminance(base)
        for rgb in seq:
            y = get_luminance(rgb)
            if abs(base_y - y) >= 108:
                return tuple(rgb)

        return (255, 255, 255) if base_y < 128 else (0, 0, 0)

    def get_sync_id_from_member(self, member: hikari.Member) -> str:
        sync_id = self.bot._sync_ids.get(member.id)

        if not sync_id and (
            member.presence
            and member.presence.activities
            and utils.get(
                member.presence.activities,
                type=hikari.ActivityType.LISTENING,
                name="Spotify",
            )
        ):
            raise LocalFilesDetected("Local files aren't supported...")

        if not sync_id:
            raise NoSpotifyPresenceError("The member has no spotify presences")

        return sync_id

    # pylint: disable=redefined-builtin
    def _get_id(self, type: str, query: str) -> str:
        if self.rest.spotipy._is_uri(query):
            return self.rest.spotipy._get_id(type, query)

        if (match := SPOTIFY_URL.match(query)) and (id := match.groupdict()["id"]):
            return id

        raise RuntimeError("Couldn't resolve ID")

    # pylint: disable=redefined-builtin
    def get_item(
        self, ctx: Context, id_or_query: str, type: typing.Type[T]
    ) -> typing.Coroutine[typing.Any, typing.Any, typing.Optional[T]]:
        type_name = get_type_name(type)
        try:
            id = self._get_id(type_name, id_or_query)
        except RuntimeError:
            return self.search_and_pick_item(ctx, id_or_query, type, type_name)
        else:
            return self.get_item_from_id(id, type, type_name)

    async def get_item_from_id(
        self, _id: str, /, type: typing.Type[T], type_name: typing.Optional[str] = None
    ) -> T:
        if type_name is None:
            type_name = get_type_name(type)

        item = getattr(self.cache, type_name + "s").get(_id)

        if item:
            return item

        res = await getattr(self.rest, type_name)(_id)
        item = self.cache.set_item(type.from_dict(self, res))
        return item

    async def search(
        self, q: str, /, type: typing.Type[T], type_name: typing.Optional[str] = None
    ) -> typing.List[T]:
        if type_name is None:
            type_name = get_type_name(type)

        plural = type_name + "s"
        queries = self.cache.get_queries(type_name)
        ids = queries.get(q)

        if ids is not None:
            items: typing.List[T] = []
            item_cache = getattr(self.cache, plural)
            for id in ids:
                item = item_cache.get(id)

                if not item:
                    break

                items.append(item)
            else:
                return items

        res = await self.rest.search(q, 10, 0, type_name, None)
        items = [type.from_dict(self, track) for track in res[plural]["items"]]
        self.cache.update_items(items)
        queries[q] = [item.id for item in items]
        return items

    async def search_and_pick_item(
        self,
        ctx: Context,
        q: str,
        /,
        type: typing.Type[T],
        type_name: typing.Optional[str] = None,
    ) -> typing.Optional[T]:
        if type_name is None:
            type_name = get_type_name(type)
        tnf: typing.Dict[str, typing.Tuple[typing.Tuple[str, str], str]] = {
            "track": (
                ("Choose a Track", "No track was found..."),
                "{item.artists_str} - {item.title}",
            ),
            "artist": (("Choose an Artist", "No artist was found..."), "{item}"),
        }
        items = await self.search(q, type, type_name)
        title, format = tnf[type_name]
        return await self.pick_from_sequence(ctx, q, items, title, format)

    async def pick_from_sequence(
        self,
        ctx: Context,
        query: str,
        /,
        seq: typing.Sequence[T],
        title: typing.Tuple[str, str],
        format: str,
    ) -> typing.Optional[T]:
        ret = None

        if not seq:
            await ctx.respond("Couldn't find anything...")
            return ret

        if len(seq) == 1:
            return seq[0]

        # This if statement adds an overhead, but w/e
        if (
            len(entries := [i for i in seq if str(i).lower() == query.lower()]) == 1
            or len(entries := [i for i in seq if fuzz.ratio(str(i), query) >= 75]) == 1
        ):
            return entries[0]

        embed = hikari.Embed(
            title=title[0] if seq else title[1],
            description="\n".join(
                f"{idx}. {format.format(item=item)}"
                for idx, item in enumerate(seq, start=1)
            ),
        )

        respond = await ctx.respond(embed=embed)

        with suppress(asyncio.TimeoutError):
            msg = await self.bot.wait_for(
                hikari.GuildMessageCreateEvent,
                predicate=lambda m: m.author.id == ctx.author.id
                and m.channel_id == ctx.channel_id,
                timeout=60,
            )

            if msg.content.isdigit():
                index = int(msg.content) - 1
                if index >= len(seq):
                    await ctx.respond(f"Number should be from 1 to {len(seq)}")
                else:
                    ret = seq[index]

        await respond.delete()

        return ret

    async def get_audio_features(self, _id: str) -> AudioFeatures:
        audio_features = self.cache.audio_features.get(_id)

        if audio_features:
            return audio_features

        res = (await self.rest.audio_features([_id]))[0]
        audio_features = AudioFeatures.from_dict(self, res)
        self.cache.set_item(audio_features)
        return audio_features

    async def get_top_tracks(
        self, artist_id: str, country: str = "US"
    ) -> typing.List[Track]:
        ids = self.cache.top_tracks.get(artist_id)
        if ids is not None:
            top_tracks: typing.List[Track] = []
            track_cache = self.cache.tracks
            for id in ids:
                track = track_cache.get(id)

                if not track:
                    break

                top_tracks.append(track)
            else:
                return top_tracks

        res = await self.rest.artist_top_tracks(artist_id, country)
        top_tracks = [Track.from_dict(self, track) for track in res["tracks"]]
        self.cache.update_items(top_tracks)
        self.cache.top_tracks[artist_id] = [track.id for track in top_tracks]
        return top_tracks
