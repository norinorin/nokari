import datetime
import operator
import os
import types
import typing
from functools import partial
from io import BytesIO

import hikari
import lightbulb
from lightbulb import Bot, plugins
from sphobjinv import Inventory

from nokari import core, utils
from nokari.core import Context
from nokari.utils import (
    Paginator,
    algorithm,
    chunk_from_list,
    converters,
    get_timestamp,
    plural,
)
from nokari.utils.formatter import discord_timestamp
from nokari.utils.parser import ArgumentParser
from nokari.utils.spotify import (
    Album,
    Artist,
    NoSpotifyPresenceError,
    SpotifyClient,
    Track,
)

api = plugins.Plugin("API", None, True)
SPOTIFY_PARSER: ArgumentParser = (
    utils.ArgumentParser()
    .style("--style", "-s", argmax=1, default="2")
    .hidden("--hidden", "-h", argmax=0)
    .card("--card", "-c", argmax=0)
    .time("--time", "-t", argmax=0)
    .color("--color", "--colour", "-cl", argmax=1)
    .member("--member", "-m", argmax=0)
    .album("--album", "-a", argmax=0)
)
SPOTIFY_VARS: typing.Tuple[str, str] = (
    "SPOTIPY_CLIENT_ID",
    "SPOTIPY_CLIENT_SECRET",
)


async def send_spotify_card(
    ctx: Context,
    args: types.SimpleNamespace,
    *,
    data: typing.Union[hikari.Member, Track],
) -> None:
    style_map = {
        "dynamic": "1",
        "fixed": "2",
        **{s: s for n in range(1, 3) if (s := str(n))},
    }
    style = style_map.get(args.style, "2")

    async with ctx.bot.rest.trigger_typing(ctx.channel_id):
        with BytesIO() as fp:
            await api.d.spotify_client(
                fp,
                data,
                args.hidden,
                args.color,
                style,
            )

            kwargs: typing.Dict[str, typing.Any] = {
                "attachment": hikari.Bytes(fp, f"{data}-card.png")
            }

            # if random.randint(0, 101) < 25:
            #     kwargs["content"] = (
            #         kwargs.get("content") or ""
            #     ) + "\n\nHave you tried the slash version of this command?"

            await ctx.respond(**kwargs)


@api.command
@core.add_cooldown(1, 2, lightbulb.cooldowns.UserBucket)
@core.commands.command(
    "spotify",
    "Contains subcommands that utilizes Spotify API.",
    SPOTIFY_VARS,
)
@core.implements(lightbulb.commands.PrefixCommandGroup)
async def spotify(self, ctx: Context) -> None:
    """"""
    await ctx.send_help(ctx.command)


# pylint: disable=too-many-locals
@spotify.child
@core.add_cooldown(1, 2, lightbulb.cooldowns.UserBucket)
@core.option("track", "The track query.", default="", required=False)
@core.command(
    "track",
    "Shows the information of a track on Spotify.",
    aliases=["song"],
    signature="[artist URI|URL|name]",
)
@core.implements(lightbulb.commands.PrefixSubCommand)
async def spotify_track(ctx: Context) -> None:
    """
    Shows the information of a track on Spotify.
    If -c/--card flag was present, it'll make a Spotify card,
    else if -a/--album flag was present, it'll display the information of the album instead.

    If no argument was passed, the song you're listening to will be fetched if applicable.
    """
    args = SPOTIFY_PARSER.parse(ctx, ctx.options.track)

    if not args.remainder:
        data = ctx.author
    elif args.member and args.remainder:
        data = await converters.user_converter(
            converters.WrappedArg(args.remainder, ctx)
        )

        if data.is_bot:
            return await ctx.respond("I won't make a card for bots >:(")
    else:
        args.hidden = True
        maybe_track = await api.d.spotify_client.get_item(ctx, args.remainder, Track)

        if not maybe_track:
            return

        data = maybe_track

    try:
        if args.card:
            await send_spotify_card(ctx, args, data=data)
            return

        if isinstance(data, hikari.User):
            sync_id = api.d.spotify_client.get_sync_id(data)
            data = await api.d.spotify_client.get_item_from_id(sync_id, Track)

    except NoSpotifyPresenceError as e:
        raise e.__class__(
            f"{'You' if data == ctx.author else f'They ({data})'} have no Spotify activity."
        )

    if args.album:
        ctx.parsed_arg.remainder = data.album.uri
        return await spotify_album.invoke(ctx)

    audio_features = await data.get_audio_features()

    album = await api.d.spotify_client._get_album(data.album_cover_url)
    colors = api.d.spotify_client._get_colors(
        BytesIO(album), "top-bottom blur", data.album_cover_url
    )
    spotify_code_url = data.get_code_url(hikari.Color.from_rgb(*colors[0]))
    spotify_code = await api.d.spotify_client._get_spotify_code(spotify_code_url)

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
            f"on {data.formatted_url}**\n"
            f"**Release date**: {discord_timestamp(data.album.release_date, fmt='d')}",
        )
        .set_thumbnail(album)
        .set_image(spotify_code)
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
    await ctx.respond(**kwargs)


@spotify.child
@core.add_cooldown(1, 2, lightbulb.cooldowns.UserBucket)
@core.option("artist", description="The artist query.")
@core.command(
    "artist",
    "Displays the information of an artist on Spotify.",
    signature="<artist URI|URL|name>",
)
@core.implements(lightbulb.commands.PrefixSubCommand)
async def spotify_artist(ctx: Context) -> None:
    args = SPOTIFY_PARSER.parse(ctx, ctx.options.artist)

    artist = await api.d.spotify_client.get_item(ctx, args.remainder, Artist)

    if not artist:
        return

    cover: typing.Optional[bytes]
    if artist.cover_url:
        cover = await api.d.spotify_client._get_album(artist.cover_url)
        colors = api.d.spotify_client._get_colors(
            BytesIO(cover), "top-bottom blur", artist.cover_url
        )[0]
    else:
        cover = None
        colors = (0, 0, 0)

    spotify_code_url = artist.get_code_url(hikari.Color.from_rgb(*colors))
    spotify_code = await api.d.spotify_client._get_spotify_code(spotify_code_url)

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
            value=f"{plural(artist.follower_count):follower,}",
        )
        .add_field(name="Popularity", value=f"\N{fire} {artist.popularity}")
    )

    if artist.genres:
        initial_embed.add_field(name="Genres", value=", ".join(artist.genres))

    if chunk := chunks.pop(0):
        initial_embed.add_field(
            name="Top Tracks",
            value=chunk,
        )

    if chunks:
        # TODO: implement higher level API for this
        length = len(chunks) + 1
        initial_embed.set_footer(text=f"Page 1/{length}")

    paginator.add_page(initial_embed)

    for idx, chunk in enumerate(chunks, start=2):
        embed = (
            hikari.Embed(title="Top tracks cont.", description=chunk)
            .set_image(initial_embed.image)
            .set_thumbnail(initial_embed.thumbnail)
            .set_footer(text=f"Page {idx}/{length}")
        )
        paginator.add_page(embed)

    await paginator.start()


@spotify.child
@core.add_cooldown(1, 2, lightbulb.cooldowns.UserBucket)
@core.option("album", description="The album query.")
@core.command(
    "album",
    "Displays the information of an album on Spotify.",
    signature="[album URI|URL|name]",
)
@core.implements(lightbulb.commands.PrefixSubCommand)
async def spotify_album(ctx: Context) -> None:
    """
    Displays the information of an album on Spotify.
    If no argument was passed, the album of the song you're listening to will be fetched if applicable.
    """
    args = SPOTIFY_PARSER.parse(ctx, ctx.options.album)

    if args.member or not args.remainder:
        args.album = True
        return await spotify_track.invoke(ctx)

    album = await api.d.spotify_client.get_item(ctx, args.remainder, Album)

    if not album:
        return

    cover = await api.d.spotify_client._get_album(album.cover_url)
    colors = api.d.spotify_client._get_colors(
        BytesIO(cover), "top-bottom blur", album.cover_url
    )[0]

    spotify_code_url = album.get_code_url(hikari.Color.from_rgb(*colors))
    spotify_code = await api.d.spotify_client._get_spotify_code(spotify_code_url)

    disc_offsets = {
        1: 0,
        **{
            track.disc_number + 1: idx
            for idx, track in enumerate(album.tracks, start=1)
        },
    }

    def get_disc_text(disc_number: int) -> str:
        return f"\N{OPTICAL DISC} Disc {disc_number}\n"

    chunks = chunk_from_list(
        [
            f"{get_disc_text(track.disc_number)*(len(disc_offsets) > 2 and index==1)}"
            f"{index}. {track.get_formatted_url(prepend_artists=True)}"
            for idx, track in enumerate(album.tracks, start=1)
            if (index := idx - disc_offsets[track.disc_number])
        ],
        1024,
    )

    paginator = Paginator.default(ctx)

    initial_embed = (
        hikari.Embed(title=f"{album.album_type.title()} Info")
        .set_thumbnail(cover)
        .set_image(spotify_code)
        .add_field(
            name="Name",
            value=f"{album.formatted_url} | {plural(album.total_tracks):track,}",
        )
        .add_field(
            name="Release Date",
            value=discord_timestamp(album.release_date, fmt="d"),
        )
        .add_field(name="Popularity", value=f"\N{fire} {album.popularity}")
        .add_field(name="Label", value=album.label)
        .add_field(
            name=" and ".join(album.copyrights),
            value="\n".join(
                typing.cast(typing.Sequence[str], album.copyrights.values())
            ),
        )
    )

    if album.genres:
        initial_embed.add_field(
            name="Genres",
            value=", ".join(album.genres),
        )

    initial_embed.add_field(
        name="Tracks",
        value=chunks.pop(0),
    )

    if chunks:
        length = len(chunks) + 1
        initial_embed.set_footer(text=f"Page 1/{length}")

    paginator.add_page(initial_embed)

    for idx, chunk in enumerate(chunks, start=2):
        embed = (
            hikari.Embed(title="Tracks cont.", description=chunk)
            .set_image(initial_embed.image)
            .set_thumbnail(initial_embed.thumbnail)
            .set_footer(text=f"Pages {idx}/{length}")
        )
        paginator.add_page(embed)

    await paginator.start()


@spotify.child
@core.add_cooldown(1, 4, lightbulb.cooldowns.UserBucket)
@core.command("cache", "Displays the Spotify cache.")
@core.implements(lightbulb.commands.PrefixSubCommand)
async def spotify_cache(ctx: Context) -> None:
    """Displays the Spotify cache."""
    client = api.d.spotify_client
    embed = (
        hikari.Embed(title="Spotify Cache")
        .add_field(
            name="Color",
            value=f"{plural(len(client.color_cache)):color,}",
            inline=True,
        )
        .add_field(
            name="Text",
            value=f"{plural(len(client.text_cache)):text,}",
            inline=True,
        )
        .add_field(
            name="Images",
            value=f"- {plural(len(client.album_cache)):album,}\n"
            f"- {plural(len(client.code_cache)):code,}",
            inline=True,
        )
        .add_field(
            name="Album",
            value=f"{plural(len(client.cache.albums)):object}\n"
            f"{plural(len(client.cache.get_queries('album'))):query|queries,}",
            inline=True,
        )
        .add_field(
            name="Artist",
            value=f"{plural(len(client.cache.artists)):object}\n"
            f"{plural(len(client.cache.get_queries('artist'))):query|queries,}",
            inline=True,
        )
        .add_field(
            name="Track",
            value=f"{plural(len(client.cache.tracks)):object}\n"
            f"w/{len(client.cache.audio_features)} audio features\n"
            f"{plural(len(client.cache.get_queries('track'))):query|queries,}",
            inline=True,
        )
    )

    await ctx.respond(embed=embed)


@api.command
@core.add_cooldown(1, 2, lightbulb.cooldowns.UserBucket)
@core.command(
    "rtfd",
    "Contains subcommands that links you to the specified object in the docs.",
    aliases=["rtfm"],
)
@core.implements(lightbulb.commands.PrefixCommandGroup)
async def rtfd(self, ctx: Context) -> None:
    """Contains subcommands that links you to the specified object in the docs."""
    await ctx.send_help(ctx.command)


@rtfd.child
@core.add_cooldown(1, 2, lightbulb.cooldowns.UserBucket)
@core.option("object", "The object query.", default="")
@core.command(
    "hikari", "Returns jump links to the specified object in Hikari docs page."
)
@core.implements(lightbulb.commands.PrefixSubCommand)
async def rtfd_hikari(ctx: Context) -> None:
    """Returns jump links to the specified object in Hikari docs page."""

    BASE_URL = "https://hikari-py.dev"

    if not ctx.options.object:
        await ctx.respond(f"{BASE_URL}/hikari")
        return

    if not api.d.hikari_objects:
        api.d.hikari_objects = {
            (name, f"[`{name}`]({BASE_URL}/{hikari_obj.uri.rstrip('#$')})")
            for hikari_obj in (
                await ctx.bot.loop.run_in_executor(
                    ctx.bot.executor,
                    partial(Inventory, url=f"{BASE_URL}/objects.inv"),
                )
            ).objects
            if (name := hikari_obj.name)
        }

    if not (
        entries := [
            url
            for _, url in algorithm.search(
                api.d.hikari_objects, ctx.options.object, key=operator.itemgetter(0)
            )
        ]
    ):
        raise RuntimeError("Couldn't find anything...")

    chunks = chunk_from_list(entries, 2_048)
    length = len(chunks)
    paginator = Paginator.default(ctx)

    for idx, chunk in enumerate(chunks, start=1):
        paginator.add_page(
            hikari.Embed(description=chunk)
            .set_footer(text=f"Page {idx}/{length}")
            .set_author(name="Hikari", url=BASE_URL, icon=f"{BASE_URL}/logo.png")
        )

    await paginator.start()


def load(bot: Bot) -> None:
    bot.add_plugin(api)
    if not hasattr(bot, "spotify_client") and all(
        var in os.environ for var in SPOTIFY_VARS
    ):
        # prevent reloading from flushing the cache
        bot.spotify_client = SpotifyClient(bot)
    api.d.spotify_client = bot.spotify_client


def unload(bot: Bot) -> None:
    bot.remove_plugin("API")
