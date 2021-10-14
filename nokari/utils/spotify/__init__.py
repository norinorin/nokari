from __future__ import annotations

import asyncio
import datetime
import re
import textwrap
import time
import typing
from contextlib import suppress
from functools import partial
from io import BytesIO

import hikari
import numpy
from colorthief import ColorThief
from fuzzywuzzy import fuzz
from lightbulb import Bot, utils
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from nokari.utils import caches
from nokari.utils.algorithm import get_alt_color, get_luminance
from nokari.utils.formatter import get_timestamp as format_time
from nokari.utils.images import (
    get_dominant_color,
    has_transparency,
    right_fade,
    round_corners,
)

from .cache import SpotifyCache
from .errors import LocalFilesDetected, NoSpotifyPresenceError
from .rest import SpotifyRest
from .typings import Artist  # re-export
from .typings import (
    _RGB,
    Album,
    AudioFeatures,
    SongMetadata,
    Spotify,
    Track,
    _SpotifyCardMetadata,
)

if typing.TYPE_CHECKING:
    from nokari.core import Context

    from .typings import T

_RGBs = typing.List[_RGB]
PI_RAD: int = 180


SPOTIFY_URL = re.compile(
    r"(?:https?://)?open.spotify.com/(?:track|album|artist|playlist)/(?P<id>\w+)"
)


class SpotifyClient:
    """A class that generates Spotify cards as well as interacts with Spotify API."""

    SMALL_FONT = ImageFont.truetype("nokari/assets/fonts/arial-unicode-ms.ttf", size=40)
    BIG_FONT = ImageFont.truetype("nokari/assets/fonts/arial-unicode-ms.ttf", size=50)
    C1_BOLD_FONT = ImageFont.truetype(
        "nokari/assets/fonts/Arial-Unicode-Bold.ttf", size=100
    )
    C2_BOLD_FONT = ImageFont.truetype(
        "nokari/assets/fonts/Arial-Unicode-Bold.ttf", size=60
    )
    SIDE_GAP = 50
    WIDTH = 1_280

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.cache = SpotifyCache()
        self.rest = SpotifyRest()

    @staticmethod
    def _get_timestamp(spotify: Spotify) -> typing.Tuple[str, str, float]:
        """Gets the timestamp of the playing song."""

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
        """Generates a rounded rectangle image."""
        base = Image.new("RGBA", size, fill)
        corner = Image.new("RGBA", (rad,) * 2, (0,) * 4)
        draw = ImageDraw.Draw(corner)
        draw.pieslice([*(0,) * 2, *(rad * 2,) * 2], PI_RAD, PI_RAD * 3 / 2, fill=fill)

        for i, coord in enumerate(
            zip([*(0,) * 2, *(size[0] - rad,) * 2], [0, *(size[1] - rad,) * 2, 0])
        ):
            base.paste(corner.rotate(i * 90), coord)

        return base

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
        colors = await self.bot.loop.run_in_executor(
            self.bot.executor, self._get_colors, album, mode, album_url
        )
        return colors, Image.open(album).convert("RGBA").resize((height,) * 2)

    @caches.cache(20)
    @staticmethod
    def _get_colors(
        image: BytesIO,
        mode: str = "full",
        image_url: str = "",  # necessary for caching
    ) -> typing.Tuple[_RGB, _RGBs]:
        """Returns the dominant color as well as other colors present in the image."""

        def get_palette() -> _RGBs:
            color_thief = ColorThief(image)
            palette = color_thief.get_palette(color_count=5, quality=100)
            return palette

        def get_dom_color() -> typing.Optional[_RGB]:
            im = Image.open(image)
            use_mask = has_transparency(im)

            if mode == "colorthief":
                return None

            im.thumbnail((400,) * 2)
            w, h = im.size

            if "crop" in mode:
                im = im.crop((0, 0, w, h / 6))

            elif "downscale" in mode:
                im = im.resize((int(w / 2), int(h / 2)), resample=0)

            elif "left-right" in mode:
                div = w // 6
                back_im = Image.new("RGBA", (div * 2, h), 0)
                left = im.crop((0, 0, div, h))
                right = im.crop((w - div, 0, w, h))
                back_im.paste(left, (0, 0), use_mask and left)
                back_im.paste(right, (div, 0), use_mask and right)
                im = back_im

            elif "top-bottom" in mode:
                div = h // 6
                back_im = Image.new("RGBA", (w, div * 2), 0)
                top = im.crop((0, 0, w, div))
                bot = im.crop((0, h - div, w, h))
                back_im.paste(top, (0, 0), use_mask and top)
                back_im.paste(bot, (0, div), use_mask and bot)
                im = back_im

            if "blur" in mode:
                im = im.filter(ImageFilter.GaussianBlur(2))

            dom_color = get_dominant_color(im)
            im.close()
            return dom_color

        dom_color, palette = get_dom_color(), get_palette()
        if dom_color is None:
            dom_color = palette.pop(0)

        return dom_color, palette

    code_cache = _get_spotify_code.cache  # type: ignore
    album_cache = _get_album.cache  # type: ignore
    color_cache = _get_colors.cache  # type: ignore

    @typing.overload
    @staticmethod
    def _get_metrics_map(
        text: str, font: ImageFont.FreeTypeFont
    ) -> typing.Dict[str, typing.Tuple[int, int, int, int]]:
        ...

    @typing.overload
    @staticmethod
    def _get_metrics_map(
        text: str,
        font: ImageFont.FreeTypeFont,
        with_vertical_metrics: typing.Literal[True],
    ) -> typing.Dict[str, typing.Tuple[int, int, int, int]]:
        ...

    @typing.overload
    @staticmethod
    def _get_metrics_map(
        text: str,
        font: ImageFont.FreeTypeFont,
        with_vertical_metrics: typing.Literal[False],
    ) -> typing.Dict[str, typing.Tuple[int, int]]:
        ...

    @staticmethod
    def _get_metrics_map(
        text: str, font: ImageFont.FreeTypeFont, with_vertical_metrics: bool = True
    ) -> typing.Union[
        typing.Dict[str, typing.Tuple[int, int]],
        typing.Dict[str, typing.Tuple[int, int, int, int]],
    ]:
        return {
            char: (*size, size[1] - height, size[1])
            if with_vertical_metrics
            and (height := font.getmask(char).size[1]) is not None
            else size
            for char in set(text)
            if (size := font.getsize(char))
        }

    @staticmethod
    def _get_height_from_text(
        text: str,
        ref_text: str,
        map_: typing.Dict[str, typing.Tuple[int, int, int, int]],
        ref_map: typing.Dict[str, typing.Tuple[int, int, int, int]],
    ) -> int:
        idx = pos = 0
        ref_pos, *_, h = ref_map[ref_text[0]]
        threshold = len(ref_text)

        for char in text:
            char_size = map_[char]

            shift = False
            if pos + char_size[0] > ref_pos:
                idx += 1
                shift = True

            if idx == threshold:
                break

            ref_size = ref_map[ref_text[idx]]

            if shift:
                ref_pos += ref_size[0]

            pos += char_size[0]

            if (bot := ref_size[3]) > h + char_size[2]:
                h = bot

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
            canvas = Image.new("RGBA", (width, height), rgbs[0])

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

            title_c_map = SpotifyClient._get_metrics_map(
                metadata.title, self.C1_BOLD_FONT
            )
            artist_c_map = SpotifyClient._get_metrics_map(artist, self.BIG_FONT)
            album_c_map = SpotifyClient._get_metrics_map(album, self.BIG_FONT)

            title_h = self._get_height_from_text(
                artist, metadata.title, artist_c_map, title_c_map
            )
            artist_h = self._get_height_from_text(
                album, artist, album_c_map, artist_c_map
            )

            outer_gap = (
                album_cover_size
                - title_h
                - artist_h
                - max(size[1] for size in album_c_map.values())
            ) // 4

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

        return await self.bot.loop.run_in_executor(
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
            canvas = Image.new("RGBA", (width, height), rgbs[0])

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

            data[..., :-1][data[..., -1] > 0] = lighter_color

            spotify_logo = Image.fromarray(data)

            canvas.paste(spotify_logo, (self.SIDE_GAP,) * 2, spotify_logo)

            draw = ImageDraw.Draw(canvas)

            spotify_text = "Spotify \u2022"

            spotify_album_c_mapping = SpotifyClient._get_metrics_map(
                spotify_text + metadata.album, self.SMALL_FONT, False
            )

            # pylint: disable=unsubscriptable-object
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

        return await self.bot.loop.run_in_executor(self.bot.executor, wrapper, metadata)

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

    def _get_data(self, data: typing.Union[hikari.User, Track]) -> SongMetadata:
        timestamp = None

        if isinstance(data, hikari.User):
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

        return SongMetadata(album, album_cover_url, artists, timestamp, title)

    async def generate_spotify_card(
        self,
        buffer: BytesIO,
        data: typing.Union[hikari.User, Track],
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

            canvas = await self.bot.loop.run_in_executor(self.bot.executor, wrapper)

        def save() -> None:
            canvas.save(buffer, "PNG")
            buffer.seek(0)

        await self.bot.loop.run_in_executor(self.bot.executor, save)

    __call__ = generate_spotify_card

    @typing.overload
    def _get_spotify_act(
        self, user: hikari.User, raise_if_none: typing.Literal[True] = True
    ) -> Spotify:
        ...

    @typing.overload
    def _get_spotify_act(
        self, user: hikari.User, raise_if_none: typing.Literal[False]
    ) -> typing.Optional[Spotify]:
        ...

    def _get_spotify_act(
        self, user: typing.Any, raise_if_none: typing.Any = True
    ) -> typing.Any:
        exc = NoSpotifyPresenceError("The member has no Spotify presences")

        if not (seq := self.bot.cache._presences_garbage.get(user.id)):
            raise exc

        if not (presence := next(iter(seq)).build_entity(self.bot)).activities:
            raise exc

        if (
            act := utils.find(
                presence.activities,
                lambda x: x.name
                and x.name == "Spotify"
                and x.type is hikari.ActivityType.LISTENING,
            )
        ) is None and raise_if_none:
            raise exc

        return act and Spotify(act)

    @staticmethod
    def _get_font_color(
        base: typing.Sequence[int], seq: typing.Sequence[typing.Sequence[int]]
    ) -> typing.Tuple[int, ...]:
        """Gets the font color."""
        base_y = get_luminance(base)
        for rgb in seq:
            y = get_luminance(rgb)
            if abs(base_y - y) >= 108:
                return tuple(rgb)

        return (255, 255, 255) if base_y < 128 else (0, 0, 0)

    def get_sync_id(self, user: hikari.User) -> str:
        sync_id = self.bot._sync_ids.get(user.id)

        try:
            spotify: typing.Optional[Spotify] = self._get_spotify_act(user)
        except NoSpotifyPresenceError:
            spotify = None

        if not sync_id and spotify:
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
        if not id_or_query:
            raise RuntimeError("Please pass in either URI/URL/name.")

        try:
            id = self._get_id(type.type, id_or_query)
        except RuntimeError:
            return self.search_and_pick_item(ctx, id_or_query, type)
        else:
            return self.get_item_from_id(id, type)

    async def get_item_from_id(self, _id: str, /, type: typing.Type[T]) -> T:
        item = getattr(self.cache, type.type + "s").get(_id)

        if item:
            return item

        res = await getattr(self.rest, type.type)(_id)
        item = self.cache.set_item(type.from_dict(self, res))
        return item

    async def search(self, q: str, /, type: typing.Type[T]) -> typing.List[T]:
        plural = type.type + "s"
        queries = self.cache.get_queries(type.type)
        q = q.lower()
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

        res = await self.rest.search(q, 10, 0, type.type, None)
        raw_items = res[plural]["items"]
        queries[q] = ids = [item["id"] for item in raw_items]

        if type is Album:
            if not ids:
                return []

            res = await self.rest.albums(ids)
            raw_items = res[plural]

        items = [type.from_dict(self, item) for item in raw_items]
        self.cache.update_items(items)
        return items

    async def search_and_pick_item(
        self,
        ctx: Context,
        q: str,
        /,
        type: typing.Type[T],
    ) -> typing.Optional[T]:
        tnf: typing.Dict[str, typing.Tuple[typing.Tuple[str, str], str]] = {
            "track": (
                ("Choose a track", "No track was found..."),
                "{item.artists_str} - {item.title}",
            ),
            "artist": (("Choose an artist", "No artist was found..."), "{item}"),
            "album": (
                ("Choose an album", "No album was found..."),
                "{item.artists_str} - {item}",
            ),
        }
        items = await self.search(q, type)
        title, format = tnf[type.type]
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
        if not (length := len(seq)):
            await ctx.respond(title[1])
            return None

        if length == 1:
            return seq[0]

        # This if statement adds an overhead, but w/e
        if (
            len(entries := [i for i in seq if str(i).lower() == query.lower()]) == 1
            or len(entries := [i for i in seq if fuzz.ratio(str(i), query) >= 75]) == 1
        ):
            return entries[0]

        custom_id = f"{int(time.time())}-select-spotify-item"
        shorten = partial(textwrap.shorten, width=100, placeholder="...")
        menu = (
            self.bot.rest.build_action_row()
            .add_select_menu(custom_id)
            .set_min_values(1)
            .set_max_values(1)
            .set_placeholder(shorten(f"1. {format.format(item=seq[0])}"))
        )

        for idx, item in enumerate(seq, start=1):
            menu.add_option(
                shorten(f"{idx}. {format.format(item=item)}"), str(idx - 1)
            ).add_to_menu()

        respond = await ctx.respond(
            content=title[not seq], component=menu.add_to_container()
        )

        with suppress(asyncio.TimeoutError):
            event = await self.bot.wait_for(
                hikari.InteractionCreateEvent,
                predicate=lambda e: isinstance(
                    e.interaction, hikari.ComponentInteraction
                )
                and e.interaction.message.id == respond.id
                and e.interaction.user.id == ctx.author.id
                and e.interaction.channel_id == ctx.channel_id
                and e.interaction.custom_id == custom_id,
                timeout=60,
            )
            ctx.interaction = interaction = event.interaction
            await interaction.create_initial_response(
                response_type=hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
            )
            return seq[int(interaction.values[0])]

        await respond.delete()

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
