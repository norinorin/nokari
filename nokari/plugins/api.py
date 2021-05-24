import datetime
import time
import types
import typing
from contextlib import suppress
from functools import partial
from io import BytesIO

import hikari
import lightbulb
from fuzzywuzzy import fuzz
from hikari.embeds import EmbedImage
from hikari.files import AsyncReader
from lightbulb import Bot, Context, plugins
from lightbulb.errors import ConverterFailure
from sphobjinv import Inventory

from nokari import core, utils
from nokari.utils import Paginator, chunk_from_list, converters, get_timestamp, plural
from nokari.utils.parser import ArgumentParser
from nokari.utils.spotify import (
    Album,
    Artist,
    NoSpotifyPresenceError,
    SpotifyClient,
    Track,
)


class API(plugins.Plugin):
    """A plugin that utilizes external APIs."""

    _spotify_argument_parser: typing.ClassVar[ArgumentParser] = (
        utils.ArgumentParser()
        .style("--style", "-s", argmax=1, default="2")
        .hidden("--hidden", "-h", argmax=0)
        .card("--card", "-c", argmax=0)
        .time("--time", "-t", argmax=0)
        .color("--color", "--colour", "-cl", argmax=1)
        .member("--member", "-m", argmax=0)
        .album("--album", "-a", argmax=0)
    )

    def __init__(self, bot: Bot) -> None:
        super().__init__()
        self.bot = bot

        if not hasattr(bot, "spotify_client"):
            # prevent reloading from flushing the cache
            self.bot.spotify_client = SpotifyClient(bot)

    @property
    def spotify_client(self) -> SpotifyClient:
        return self.bot.spotify_client

    async def send_spotify_card(
        self,
        ctx: Context,
        args: types.SimpleNamespace,
        *,
        data: typing.Union[hikari.Member, Track],
    ) -> None:
        if args.time:
            t0 = time.time()

        style_map = {
            "dynamic": "1",
            "fixed": "2",
            **{s: s for n in range(1, 3) if (s := str(n))},
        }
        style = style_map.get(args.style, "2")

        async with self.bot.rest.trigger_typing(ctx.channel_id):
            with BytesIO() as fp:
                await self.spotify_client(
                    fp,
                    data,
                    args.hidden
                    or not (args.member or (not args.member and not args.remainder)),
                    args.color,
                    style,
                )

                kwargs: typing.Dict[str, typing.Any] = {
                    "attachment": hikari.Bytes(fp, f"{data}-card.png")
                }
                if args.time:
                    kwargs["initial_time"] = t0

                # if random.randint(0, 101) < 25:
                #     kwargs["content"] = (
                #         kwargs.get("content") or ""
                #     ) + "\n\nHave you tried the slash version of this command?"

                await ctx.respond(**kwargs)

    @core.commands.group()
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify(self, ctx: Context) -> None:
        """Contains subcommands that utilizes Spotify API."""
        await ctx.send_help(ctx.command)

    # pylint: disable=too-many-locals
    @spotify.command(name="track", aliases=["song"], usage="<artist URI|URL|name>")
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify_track(
        self, ctx: Context, *, arguments: typing.Optional[str] = None
    ) -> None:
        """
        Shows the information of a track on Spotify.
        If -c/--card flag was present, it'll make a Spotify card.
        Else if -a/--album flag was present, it'll display the information of the album instead.
        """
        args = self._spotify_argument_parser.parse(arguments or "")

        if args.time:
            t0 = time.time()

        if args.member or (not args.member and not args.remainder):
            data: typing.Union[hikari.Member, Track] = ctx.member
            with suppress(ConverterFailure):
                data = await converters.member_converter(
                    converters.WrappedArg(args.remainder, ctx)
                )

                if data.is_bot:
                    return await ctx.respond("I won't make a card for bots >:(")
        else:
            maybe_track = await self.spotify_client.get_item(ctx, args.remainder, Track)

            if not maybe_track:
                return

            data = maybe_track

        try:
            if args.card:
                await self.send_spotify_card(ctx, args, data=data)
                return

            if isinstance(data, hikari.Member):
                sync_id = self.spotify_client.get_sync_id_from_member(data)
                data = await self.spotify_client.get_item_from_id(sync_id, Track)

        except NoSpotifyPresenceError as e:
            raise e.__class__(
                f"{'You' if data == ctx.author else 'They'} have no Spotify activity"
            )

        if args.album:
            return await self.spotify_album.invoke(ctx, arguments=data.album.uri)

        audio_features = await data.get_audio_features()

        album = await self.spotify_client._get_album(data.album_cover_url)
        colors = self.spotify_client._get_colors(
            BytesIO(album), "top-bottom blur", data.album_cover_url
        )
        spotify_code_url = data.get_code_url(hikari.Color.from_rgb(*colors[0]))
        spotify_code = await self.spotify_client._get_spotify_code(spotify_code_url)

        invoked_with = (
            ctx.content[len(ctx.prefix) + len(ctx.invoked_with) :]
            .strip()
            .split(maxsplit=1)[0]
        )
        embed = (
            hikari.Embed(
                title=f"{invoked_with.capitalize()} Info",
                description=f"**[#{data.track_number}]({data.album.url}) {data.formatted_url} by "
                f"{', '.join(artist.formatted_url for artist in data.artists)} "
                f"on {data.formatted_url}**\n",
                timestamp=data.album.release_date,
            )
            .set_thumbnail(album)
            .set_image(spotify_code)
            .set_footer(text="Released on")
        )

        round_ = lambda n: int(round(n))

        for k, v in {
            "Key": audio_features.get_key(),
            "Tempo": f"{round_(audio_features.tempo)} BPM",
            "Duration": get_timestamp(
                datetime.timedelta(seconds=audio_features.duration_ms / 1000)
            ),
            "Camelot": audio_features.get_camelot(),
            "Loudness": f"{round(audio_features.loudness, 1)} dB",
            "Time Signature": f"{audio_features.time_signature}/4",
            "Album Type": f"{data.album.album_type.capitalize()}",
            "Popularity": f"\N{fire} {data.popularity}",
        }.items():
            embed.add_field(name=k, value=v, inline=True)

        for attr in (
            "danceability",
            "energy",
            "speechiness",
            "acousticness",
            "instrumentalness",
            "liveness",
            "valence",
        ):
            embed.add_field(
                name=attr.capitalize(),
                value=str(round_(getattr(audio_features, attr) * 100)),
                inline=True,
            )

        kwargs: typing.Dict[str, typing.Any] = dict(embed=embed)

        if args.time:
            kwargs["initial_time"] = t0

        await ctx.respond(**kwargs)

    @spotify.command(name="artist", usage="<artist URI|URL|name>")
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify_artist(self, ctx: Context, *, arguments: str) -> None:
        """
        Displays the information of an artist on Spotify.
        """
        args = self._spotify_argument_parser.parse(arguments)

        if args.time:
            t0 = time.time()

        artist = await self.spotify_client.get_item(ctx, args.remainder, Artist)

        if not artist:
            return

        if artist.cover_url:
            cover: typing.Optional[bytes] = await self.spotify_client._get_album(
                artist.cover_url
            )
            colors = self.spotify_client._get_colors(
                BytesIO(typing.cast(bytes, cover)), "top-bottom blur", artist.cover_url
            )[0]
        else:
            cover = None
            colors = (0, 0, 0)

        spotify_code_url = artist.get_code_url(hikari.Color.from_rgb(*colors))
        spotify_code = await self.spotify_client._get_spotify_code(spotify_code_url)

        top_tracks = await artist.get_top_tracks()
        chunks = chunk_from_list(
            [
                f"{idx}. {track.formatted_url} - \N{fire} {track.popularity}"
                for idx, track in enumerate(top_tracks, start=1)
            ],
            1024,
        )

        paginator = Paginator.default(ctx)

        initial_embed = (
            hikari.Embed(title="Artist Info")
            .set_thumbnail(cover)
            .set_image(spotify_code)
            .add_field(name="Name", value=artist.formatted_url)
            .add_field(
                name="Follower Count",
                value=f"{plural(artist.follower_count, _format=True):follower}",
            )
            .add_field(name="Popularity", value=f"\N{fire} {artist.popularity}")
            .add_field(
                name="Genres",
                value=", ".join(artist.genres) if artist.genres else "Not available...",
            )
            .add_field(
                name="Top Tracks",
                value=chunks.pop(0),
            )
        )

        paginator.add_page(initial_embed)

        image = typing.cast(EmbedImage[AsyncReader], initial_embed.image)
        thumbnail = typing.cast(EmbedImage[AsyncReader], initial_embed.thumbnail)

        for chunk in chunks:
            embed = (
                hikari.Embed(
                    title="Top tracks cont.", description=chunk, color=ctx.color
                )
                .set_image(image)
                .set_thumbnail(thumbnail)
            )
            paginator.add_page(embed)

        if args.time:
            paginator.set_initial_kwarg(initial_time=t0)

        await paginator.start()

    @spotify.command(name="album", usage="<album URI|URL|name>")
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify_album(self, ctx: Context, *, arguments: str) -> None:
        """Displays the information of an album on Spotify."""
        args = self._spotify_argument_parser.parse(arguments)

        if args.time:
            t0 = time.time()

        album = await self.spotify_client.get_item(ctx, args.remainder, Album)

        if not album:
            return

        cover: typing.Optional[bytes] = await self.spotify_client._get_album(
            album.cover_url
        )
        colors = self.spotify_client._get_colors(
            BytesIO(typing.cast(bytes, cover)), "top-bottom blur", album.cover_url
        )[0]

        spotify_code_url = album.get_code_url(hikari.Color.from_rgb(*colors))
        spotify_code = await self.spotify_client._get_spotify_code(spotify_code_url)

        chunks = chunk_from_list(
            [
                f"{idx}. {track.get_formatted_url(prepend_artists=True)}"
                for idx, track in enumerate(album.tracks, start=1)
            ],
            1024,
        )

        paginator = Paginator.default(ctx)

        initial_embed = (
            hikari.Embed(
                title=f"{album.album_type.title()} Info", timestamp=album.release_date
            )
            .set_thumbnail(cover)
            .set_image(spotify_code)
            .add_field(
                name="Name",
                value=f"{album.formatted_url} | {plural(album.total_tracks):track}",
            )
            .add_field(name="Popularity", value=f"\N{fire} {album.popularity}")
            .add_field(name="Label", value=album.label)
        )

        if album.copyright:
            initial_embed.add_field(name="Copyright", value=album.copyright)

        if album.phonogram:
            initial_embed.add_field(name="Phonogram", value=album.phonogram)

        (
            initial_embed.add_field(
                name="Genres",
                value=", ".join(album.genres) if album.genres else "Not available...",
            )
            .add_field(
                name="Tracks",
                value=chunks.pop(0),
            )
            .set_footer(text="Released on")
        )

        paginator.add_page(initial_embed)

        image = typing.cast(EmbedImage[AsyncReader], initial_embed.image)
        thumbnail = typing.cast(EmbedImage[AsyncReader], initial_embed.thumbnail)

        for chunk in chunks:
            embed = (
                hikari.Embed(title="Tracks cont.", description=chunk, color=ctx.color)
                .set_image(image)
                .set_thumbnail(thumbnail)
            )
            paginator.add_page(embed)

        if args.time:
            paginator.set_initial_kwarg(initial_time=t0)

        await paginator.start()

    @spotify.command(name="playlist")
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify_playlist(self, ctx: Context) -> None:
        """Not implemented yet."""

    @spotify.command(name="user")
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify_user(self, ctx: Context) -> None:
        """Not implemented yet."""

    @spotify.command(name="cache")
    @core.cooldown(1, 4, lightbulb.cooldowns.UserBucket)
    async def spotify_cache(self, ctx: Context) -> None:
        """Displays the Spotify cache."""
        client = self.spotify_client
        embed = (
            hikari.Embed(title="Spotify Cache")
            .add_field(
                name="Color",
                value=f"{plural(len(client.color_cache)):color}",
                inline=True,
            )
            .add_field(
                name="Text", value=f"{plural(len(client.text_cache)):text}", inline=True
            )
            .add_field(
                name="Images",
                value=f"- {plural(len(client.album_cache)):album}\n"
                f"- {plural(len(client.code_cache)):code}",
                inline=True,
            )
            .add_field(
                name="Album",
                value=f"{plural(len(client.cache.albums)):object}\n"
                f"{plural(len(client.cache.get_queries('album'))):query|queries}",
                inline=True,
            )
            .add_field(
                name="Artist",
                value=f"{plural(len(client.cache.artists)):object}\n"
                f"{plural(len(client.cache.get_queries('artist'))):query|queries}",
                inline=True,
            )
            .add_field(
                name="Track",
                value=f"{plural(len(client.cache.tracks)):object}\n"
                f"w/{len(client.cache.audio_features)} audio features\n"
                f"{plural(len(client.cache.get_queries('track'))):query|queries}",
                inline=True,
            )
        )

        await ctx.respond(embed=embed)

    @core.commands.group(aliases=["rtfm"])
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def rtfd(self, ctx: Context) -> None:
        """Contains subcommands that links you to the specified object in the docs."""
        await ctx.send_help(ctx.command)

    @rtfd.command(name="hikari")
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def rtfd_hikari(self, ctx: Context, obj: typing.Optional[str] = None) -> None:
        """Returns jump links to the specified object in Hikari docs page."""

        BASE_URL = "https://hikari-py.github.io/hikari"

        if not obj:
            await ctx.respond(BASE_URL)
            return

        if not hasattr(self, "hikari_inv"):
            inv = partial(Inventory, url=f"{BASE_URL}/objects.inv")
            self.hikari_inv = await self.bot.loop.run_in_executor(
                self.bot.executor, inv
            )

        entries = [
            f"[`{name}`]({BASE_URL}/{hikari_obj.uri.rstrip('#$')}#{name})"
            for hikari_obj in self.hikari_inv.objects
            if fuzz.token_set_ratio(obj, hikari_obj.name.rsplit(".")[-1]) >= 75
            and (name := hikari_obj.name)
        ]

        if not entries:
            raise RuntimeError("Couldn't find anything...")

        chunks = chunk_from_list(entries, 2048)
        length = len(chunks)
        paginator = Paginator.default(ctx)

        for idx, chunk in enumerate(chunks, start=1):
            paginator.add_page(
                hikari.Embed(description=chunk, color=ctx.color)
                .set_footer(text=f"Page {idx}/{length}")
                .set_author(name="Hikari", url=BASE_URL, icon=f"{BASE_URL}/logo.png")
            )

        await paginator.start()


def load(bot: Bot) -> None:
    bot.add_plugin(API(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("API")
