import datetime
import time
import types
import typing
from contextlib import suppress
from io import BytesIO

import hikari
import lightbulb
from hikari.embeds import EmbedImage
from hikari.files import AsyncReader
from lightbulb import Bot, Context, plugins
from lightbulb.errors import ConverterFailure

from nokari import core, utils
from nokari.utils import Paginator, chunk_from_list, converters, get_timestamp, plural
from nokari.utils.spotify import (
    Artist,
    NoSpotifyPresenceError,
    SpotifyCardGenerator,
    Track,
)


class API(plugins.Plugin):
    """A plugin that utilizes external APIs"""

    def __init__(self, bot: Bot) -> None:
        super().__init__()
        self.bot = bot
        self.spotify_card_generator = SpotifyCardGenerator(bot)
        self._spotify_argument_parser = (
            utils.ArgumentParser()
            .argument("style", "--style", "-s", argmax=1, default="2")
            .argument("hidden", "--hidden", "-h", argmax=0)
            .argument("card", "--card", "-c", argmax=0)
            .argument("time", "--time", "-t", argmax=0)
            .argument("color", ["--color", "--colour"], "-cl", argmax=1)
            .argument("member", "--member", "-m", argmax=0)
        )

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
                await self.spotify_card_generator(
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
    @spotify.command(name="track", aliases=["song"])
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify_track(
        self, ctx: Context, *, arguments: typing.Optional[str] = None
    ) -> None:
        """
        Shows the information of a Spotify track. If -c/--card flag was present,
        it'll make a Spotify card.
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
            maybe_track = await self.spotify_card_generator.get_item(
                ctx, args.remainder, Track
            )

            if not maybe_track:
                return

            data = maybe_track

        try:
            if args.card:
                await self.send_spotify_card(ctx, args, data=data)
                return

            if isinstance(data, hikari.Member):
                sync_id = self.spotify_card_generator.get_sync_id_from_member(data)
                data = await self.spotify_card_generator.get_track_from_id(sync_id)

        except NoSpotifyPresenceError as e:
            raise e.__class__(
                f"{'You' if data == ctx.author else 'They'} have no Spotify activity"
            )

        audio_features = await data.get_audio_features()

        album = await self.spotify_card_generator._get_album(data.album_cover_url)
        colors = self.spotify_card_generator._get_colors(
            BytesIO(album), "top-bottom blur", data.album_cover_url
        )
        spotify_code_url = data.get_code_url(hikari.Color.from_rgb(*colors[0]))
        spotify_code = await self.spotify_card_generator._get_spotify_code(
            spotify_code_url
        )

        invoked_with = (
            ctx.content[len(ctx.prefix) + len(ctx.invoked_with) :]
            .strip()
            .split(maxsplit=1)[0]
        )
        embed = (
            hikari.Embed(
                title=f"{invoked_with.capitalize()} Info",
                description=f"**{data.formatted_url} [#{data.track_number}]({data.album.url}) by "
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

    @spotify.command(name="artist", hidden=True)
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify_artist(self, ctx: Context, *, arguments: str) -> None:
        """
        Displays the information of a Spotify track. If -c/--card flag was present,
        it'll make a Spotify card.
        """
        args = self._spotify_argument_parser.parse(arguments)

        if args.time:
            t0 = time.time()

        artist = await self.spotify_card_generator.get_item(ctx, args.remainder, Artist)

        if not artist:
            return

        if artist.cover_url:
            cover: typing.Optional[
                bytes
            ] = await self.spotify_card_generator._get_album(artist.cover_url)
            colors = self.spotify_card_generator._get_colors(
                BytesIO(typing.cast(bytes, cover)), "top-bottom blur", artist.cover_url
            )[0]
        else:
            cover = None
            colors = (0, 0, 0)

        spotify_code_url = artist.get_code_url(hikari.Color.from_rgb(*colors))
        spotify_code = await self.spotify_card_generator._get_spotify_code(
            spotify_code_url
        )

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

    @spotify.command(name="album")
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify_album(self, ctx: Context) -> None:
        """Not implemented yet."""

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
        gen = self.spotify_card_generator
        embed = (
            hikari.Embed(title="Spotify Cache")
            .add_field(
                name="Album",
                value=f"{plural(len(gen.album_cache)):album}",
            )
            .add_field(
                name="Color",
                value=f"{plural(len(gen.color_cache)):color}",
            )
            .add_field(
                name="Text",
                value=f"{plural(len(gen.text_cache)):text}",
            )
            .add_field(
                name="Tracks",
                value=f"- from IDs: {plural(len(gen.track_from_id_cache)):track}\n"
                f"- from queries: {plural(len(gen.track_from_query_cache)):track}",
            )
            .add_field(
                name="Artists",
                value=f"- from IDs: {plural(len(gen.artist_from_id_cache)):artist}\n"
                f"- from queries: {plural(len(gen.artist_from_query_cache)):artist}",
            )
            .add_field(
                name="Codes",
                value=f"{plural(len(gen.code_cache)):code}",
            )
        )

        await ctx.respond(embed=embed)


def load(bot: Bot) -> None:
    bot.add_plugin(API(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("API")
