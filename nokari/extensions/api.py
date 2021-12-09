import datetime
import operator
import os
from functools import partial
from io import BytesIO
from typing import Any, Iterator, Optional, Sequence, Set, Tuple, Union, cast

import hikari
from hikari.commands import CommandChoice, OptionType
from hikari.guilds import Member
from hikari.snowflakes import Snowflake
from sphobjinv import Inventory

from kita.command_handlers import GatewayCommandHandler
from kita.commands import command
from kita.cooldowns import user_hash_getter, with_cooldown
from kita.data import data
from kita.extensions import initializer
from kita.options import with_option
from kita.responses import Response, defer, respond
from nokari.core import Context, Nokari
from nokari.utils import Paginator, algorithm, chunk_from_list, get_timestamp, plural
from nokari.utils.formatter import discord_timestamp
from nokari.utils.spotify import (
    Album,
    Artist,
    NoSpotifyPresenceError,
    SpotifyClient,
    Track,
)

SPOTIFY_VARS: Tuple[str, str] = (
    "SPOTIPY_CLIENT_ID",
    "SPOTIPY_CLIENT_SECRET",
)
HAS_SPOTIFY_VARS: bool = all(var in os.environ for var in SPOTIFY_VARS)
HIKARI_BASE_URL = "https://hikari-py.dev"


class HikariObjects:
    def __init__(self) -> None:
        self.objects: Set[Tuple[str, str]] = set()

    async def init_cache(self, app: Nokari) -> None:
        self.objects = {
            (
                name := hikari_obj.name,
                f"[`{name}`]({HIKARI_BASE_URL}/{hikari_obj.uri.rstrip('#$')})",
            )
            for hikari_obj in (
                await app.loop.run_in_executor(
                    app.executor,
                    partial(Inventory, url=f"{HIKARI_BASE_URL}/objects.inv"),
                )
            ).objects
        }


if HAS_SPOTIFY_VARS:

    async def send_spotify_card(
        ctx: Context,
        spotify_client: SpotifyClient,
        member_or_track: Union[hikari.Member, Track],
        style: str,
        hidden: bool,
    ) -> None:
        style_map = {
            "dynamic": "1",
            "fixed": "2",
            **{(s := str(n)): s for n in range(1, 3)},
        }
        style = style_map.get(style, "2")

        with BytesIO() as fp:
            await spotify_client(
                fp,
                member_or_track,
                hidden,
                style,
            )

            await ctx.edit(attachment=hikari.Bytes(fp, f"{member_or_track}-card.png"))

    @command("spotify", "Spotify API-related commands.")
    def spotify() -> None:
        ...

    def _ensure_member(member: Optional[Member]) -> Member:
        if not member:
            raise RuntimeError("Couldn't resolve the member.")

        if member.is_bot:
            raise RuntimeError("I won't make a card for bots >:(")

        return member

    # pylint: disable=too-many-locals
    @spotify.command("track", "Shows the information of a track on Spotify.")
    @with_cooldown(user_hash_getter, 1, 2)
    @with_option(OptionType.STRING, "track", "The track to lookup.")
    @with_option(OptionType.USER, "member", "The member who's listening to Spotify.")
    @with_option(OptionType.BOOLEAN, "card", "Generate a Spotify card.")
    @with_option(OptionType.BOOLEAN, "album", "Send the album of the track instead.")
    @with_option(OptionType.BOOLEAN, "hidden", "Hide the progress bar.")
    @with_option(
        OptionType.STRING,
        "style",
        "The style of the card.",
        [CommandChoice(name="1", value="1"), CommandChoice(name="2", value="2")],
    )
    async def spotify_track(
        ctx: Context = data(Context),
        spotify_client: SpotifyClient = data(SpotifyClient),
        track: str = "",
        card: bool = False,
        album: bool = False,
        member: Optional[Snowflake] = None,
        hidden: bool = False,
        style: str = "1",
    ) -> Any:
        yield defer()

        member_or_track: Union[Member, Track]
        if not track:
            member_or_track = _ensure_member(ctx.interaction.member)

        elif member:
            assert ctx.interaction.resolved
            member_or_track = _ensure_member(
                ctx.interaction.resolved.members.get(member)
            )

        else:
            hidden = True
            if not (maybe_track := await spotify_client.get_item(ctx, track, Track)):
                return

            member_or_track = maybe_track

        try:
            if card:
                await send_spotify_card(
                    ctx, spotify_client, member_or_track, style, hidden
                )
                return

            if isinstance(member_or_track, hikari.User):
                sync_id = spotify_client.get_sync_id(member_or_track)
                spotify_track = await spotify_client.get_item_from_id(sync_id, Track)
            else:
                spotify_track = member_or_track

        except NoSpotifyPresenceError as e:
            raise e.__class__(
                f"{'You' if member_or_track == ctx.interaction.member else f'They ({member_or_track})'} have no Spotify activity."
            )

        if album:
            yield spotify_album(ctx, spotify_client, spotify_track.album.uri)
            return

        audio_features = await spotify_track.get_audio_features()

        album_byte = await spotify_client.get_album(spotify_track.album_cover_url)
        colors = spotify_client.get_colors(
            BytesIO(album_byte), "top-bottom blur", spotify_track.album_cover_url
        )
        spotify_code_url = spotify_track.get_code_url(hikari.Color.from_rgb(*colors[0]))
        spotify_code = await spotify_client.get_spotify_code(spotify_code_url)

        embed = (
            hikari.Embed(
                title=f"Track Info",
                description=f"**[#{spotify_track.track_number}]({spotify_track.album.url}) {spotify_track.formatted_url} by "
                f"{', '.join(artist.formatted_url for artist in spotify_track.artists)} "
                f"on {spotify_track.formatted_url}**\n"
                f"**Release date**: {discord_timestamp(spotify_track.album.release_date, fmt='d')}",
            )
            .set_thumbnail(album_byte)
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
            "Album Type": f"{spotify_track.album.album_type.capitalize()}",
            "Popularity": f"\N{fire} {spotify_track.popularity}",
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

        await ctx.edit(embed=embed)

    @spotify.command("artist", "Displays the information of an artist on Spotify.")
    @with_cooldown(user_hash_getter, 1, 2)
    @with_option(OptionType.STRING, "artist", description="The artist to lookup.")
    async def spotify_artist(
        artist: str,
        ctx: Context = data(Context),
        spotify_client: SpotifyClient = data(SpotifyClient),
    ) -> Any:
        yield defer()

        spotify_artist: Optional[Artist] = await spotify_client.get_item(
            ctx, artist, Artist
        )

        if not spotify_artist:
            return

        cover: Optional[bytes]
        if spotify_artist.cover_url:
            cover = await spotify_client.get_album(spotify_artist.cover_url)
            colors = spotify_client.get_colors(
                BytesIO(cover), "top-bottom blur", spotify_artist.cover_url
            )[0]
        else:
            cover = None
            colors = (0, 0, 0)

        spotify_code_url = spotify_artist.get_code_url(hikari.Color.from_rgb(*colors))
        spotify_code = await spotify_client.get_spotify_code(spotify_code_url)

        top_tracks = await spotify_artist.get_top_tracks()
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
            .add_field(name="Name", value=spotify_artist.formatted_url)
            .add_field(
                name="Follower Count",
                value=f"{plural(spotify_artist.follower_count):follower,}",
            )
            .add_field(name="Popularity", value=f"\N{fire} {spotify_artist.popularity}")
        )

        if spotify_artist.genres:
            initial_embed.add_field(
                name="Genres", value=", ".join(spotify_artist.genres)
            )

        if chunk := chunks.pop(0):
            initial_embed.add_field(
                name="Top Tracks",
                value=chunk,
            )

        length = 1
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

    @spotify.command("album", "Display the information of an album on Spotify.")
    @with_cooldown(user_hash_getter, 1, 2)
    @with_option(OptionType.STRING, "album", "The album to lookup")
    async def spotify_album(
        ctx: Context = data(Context),
        spotify_client: SpotifyClient = data(SpotifyClient),
        album: str = "",
    ) -> Any:
        yield defer()

        if not album:
            yield spotify_track(ctx, spotify_client, album=True)
            return

        if not (spotify_album := await spotify_client.get_item(ctx, album, Album)):
            return

        cover = await spotify_client.get_album(spotify_album.cover_url)
        colors = spotify_client.get_colors(
            BytesIO(cover), "top-bottom blur", spotify_album.cover_url
        )[0]

        spotify_code_url = spotify_album.get_code_url(hikari.Color.from_rgb(*colors))
        spotify_code = await spotify_client.get_spotify_code(spotify_code_url)

        disc_offsets = {
            1: 0,
            **{
                track.disc_number + 1: idx
                for idx, track in enumerate(spotify_album.tracks, start=1)
            },
        }

        def get_disc_text(disc_number: int) -> str:
            return f"\N{OPTICAL DISC} Disc {disc_number}\n"

        chunks = chunk_from_list(
            [
                f"{get_disc_text(track.disc_number)*(len(disc_offsets) > 2 and index==1)}"
                f"{index}. {track.get_formatted_url(prepend_artists=True)}"
                for idx, track in enumerate(spotify_album.tracks, start=1)
                if (index := idx - disc_offsets[track.disc_number])
            ],
            1024,
        )

        paginator = Paginator.default(ctx)

        initial_embed = (
            hikari.Embed(title=f"{spotify_album.album_type.title()} Info")
            .set_thumbnail(cover)
            .set_image(spotify_code)
            .add_field(
                name="Name",
                value=f"{spotify_album.formatted_url} | {plural(spotify_album.total_tracks):track,}",
            )
            .add_field(
                name="Release Date",
                value=discord_timestamp(spotify_album.release_date, fmt="d"),
            )
            .add_field(name="Popularity", value=f"\N{fire} {spotify_album.popularity}")
            .add_field(name="Label", value=spotify_album.label)
            .add_field(
                name=" and ".join(spotify_album.copyrights),
                value="\n".join(cast(Sequence[str], spotify_album.copyrights.values())),
            )
        )

        if spotify_album.genres:
            initial_embed.add_field(
                name="Genres",
                value=", ".join(spotify_album.genres),
            )

        initial_embed.add_field(
            name="Tracks",
            value=chunks.pop(0),
        )

        length = 1
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

    @spotify.command("cache", "Display the cached Spotify objects.")
    @with_cooldown(user_hash_getter, 1, 4)
    def spotify_cache(client: SpotifyClient = data(SpotifyClient)) -> Response:
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

        return respond(embed=embed)


@command("rtfd", "RTFD commands.")
def rtfd() -> None:
    ...


@rtfd.command(
    "hikari", "Return jump links to the specified object in Hikari docs page."
)
@with_cooldown(user_hash_getter, 1, 2)
@with_option(OptionType.STRING, "obj", "Hikari object to lookup.")
def rtfd_hikari(
    ctx: Context = data(Context),
    objects: HikariObjects = data(HikariObjects),
    obj: str = "",
) -> Iterator[Any]:

    if not obj:
        yield respond(f"{HIKARI_BASE_URL}/hikari")
        return

    if not objects.objects:
        # only defer when fetching the objects
        yield defer()
        yield objects.init_cache(ctx.app)

    if not (
        entries := [
            url
            for _, url in algorithm.search(
                objects.objects, obj, key=operator.itemgetter(0)
            )
        ]
    ):
        raise RuntimeError("Couldn't find anything...")  # ephemeral if not deferred

    chunks = chunk_from_list(entries, 2_048)
    length = len(chunks)
    paginator = Paginator.default(ctx)

    for idx, chunk in enumerate(chunks, start=1):
        paginator.add_page(
            hikari.Embed(description=chunk)
            .set_footer(text=f"Page {idx}/{length}")
            .set_author(
                name="Hikari", url=HIKARI_BASE_URL, icon=f"{HIKARI_BASE_URL}/logo.png"
            )
        )

    yield paginator.start()


@initializer
def extension_initializer(handler: GatewayCommandHandler) -> None:
    if HAS_SPOTIFY_VARS:
        handler.set_data(SpotifyClient(cast(Nokari, handler.app)), suppress=True)

    handler.set_data(HikariObjects(), suppress=True)
