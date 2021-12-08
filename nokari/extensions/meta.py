import inspect
import os
import sys
import time
from collections import Counter
from typing import Iterator, Optional, cast

import hikari
import psutil
from hikari.commands import OptionType

from kita.command_handlers import GatewayCommandHandler
from kita.commands import command
from kita.cooldowns import user_hash_getter, with_cooldown
from kita.data import data
from kita.extensions import finalizer, initializer
from kita.options import with_option
from kita.responses import Response, edit, respond
from nokari.core import Context
from nokari.core.bot import Nokari
from nokari.extensions.extras.admin import run_command_in_shell
from nokari.utils import converters, human_timedelta, paginator, plural, spotify


# pylint: disable=too-many-locals
def get_info(
    ctx: Context,
    app: Nokari,
    embed: hikari.Embed,
    process: psutil.Process,
    owner: bool = False,
) -> None:
    """Modify the embed to contain the statistics."""
    total_members = sum(
        [g.member_count for g in app.cache.get_available_guilds_view().values()]
    )
    channels = (
        "\n".join(
            f"{v} {str(k).split('_', 2)[-1].lower()}"
            for k, v in Counter(
                [c.type for c in app.cache.get_guild_channels_view().values()]
            ).items()
        )
        or "No cached channels..."
    )
    presences = sum([len(i) for i in app.cache.get_presences_view().values()])
    counter = Counter(
        [
            m.is_bot
            for mapping in app.cache.get_members_view().values()
            for m in mapping.values()
        ]
    )
    bots, human = counter[True], counter[False]
    boot_time = human_timedelta(
        psutil.boot_time(),
        append_suffix=False,
        brief=True,
    )
    total_servers = len(app.cache.get_available_guilds_view()) + len(
        ctx.app.cache.get_unavailable_guilds_view()
    )
    (
        embed.add_field(
            name="Uptime:",
            value=f"Bot: {ctx.app.brief_uptime}\nServer: {boot_time}",
            inline=True,
        )
        .add_field(name="Channels:", value=channels, inline=True)
        .add_field(
            name="Total servers:",
            value=f"{total_servers:,}",
            inline=True,
        )
        .add_field(
            name="Total cached members:",
            value=(
                f"{human:,}h & {bots:,}b out of {total_members:,}\n"
                f"{plural(presences):presence,} "
                f"({len(app.cache._presences_garbage):,} unique)\n"
            ),
            inline=True,
        )
        .add_field(
            name="CPU:",
            value=f"{round(process.cpu_percent()/psutil.cpu_count(), 2)}%",
            inline=True,
        )
    )

    memory_full_info = process.memory_full_info()
    if not owner:
        name = "Memory:"
        value = f"{round(memory_full_info.uss / 1_024 ** 2, 2)}MiB"
    else:
        name = "RSS / USS:"
        value = (
            f"{round(memory_full_info.rss / 1_024 ** 2, 2)}MiB "
            f"/ {round(memory_full_info.uss / 1_024 ** 2, 2)}MiB"
        )

    embed.add_field(name=name, value=value, inline=True)


def _format_latency(latency: float) -> str:
    emoji = (
        "🔴" if (latency := int(latency * 1000)) > 500 else "🟡" if latency > 100 else "🟢"
    )
    return f"{emoji} `{latency} ms`"


@command("ping", "Respond with the heartbeat latency.")
@with_cooldown(user_hash_getter, 1, 10)
def ping(ctx: Context = data(Context)) -> Iterator[Response]:
    me = ctx.app.get_me()
    assert me is not None
    embed = (
        hikari.Embed()
        .set_author(name="Ping", icon=me.avatar_url)
        .add_field("WS heartbeat latency", _format_latency(ctx.app.heartbeat_latency))
    )

    t0 = time.perf_counter()
    yield respond(embed=embed)
    rest_latency = time.perf_counter() - t0
    embed.add_field("REST latency", _format_latency(rest_latency))
    yield edit(embed=embed)


@command("stats", "Display the statistic of the bot.")
@with_cooldown(user_hash_getter, 1, 10)
def stats(
    ctx: Context = data(Context), process: psutil.Process = data(psutil.Process)
) -> Iterator[Response]:
    embed = hikari.Embed(title="Stats")
    get_info(
        ctx,
        cast(Nokari, ctx.app),
        embed,
        process,
        owner=ctx.interaction.user.id in ctx.handler.owner_ids,
    )
    yield respond(embed=embed)


@command("source", "Return the link to the source code.")
@with_cooldown(user_hash_getter, 3, 5)
@with_option(OptionType.STRING, "obj", "The object to lookup.")
async def source(ctx: Context = data(Context), obj: Optional[str] = None) -> None:
    base_url = "https://github.com/norinorin/nokari"

    if obj is None:
        await ctx.respond(base_url)
        return

    obj_map = {
        "bot": ctx.app.__class__,
        "context": ctx.__class__,
        "cache": ctx.app.cache.__class__,
        "spotify": spotify.SpotifyClient,
        "paginator": paginator.Paginator,
    }

    aliases = {"sp": "spotify", "ctx": "context"}

    obj = obj.lower()

    maybe_command = obj_map.get(aliases.get(obj, obj), ctx.handler.get_command(obj))
    if maybe_command is None:
        await ctx.respond("Couldn't find anything...")
        return

    actual_obj = getattr(maybe_command, "callback", maybe_command)

    lines, lineno = inspect.getsourcelines(actual_obj)
    hash_jump = f"#L{lineno}-L{lineno+len(lines)-1}"
    blob = os.path.relpath(sys.modules[actual_obj.__module__].__file__)

    stdout, stderr = await run_command_in_shell("git rev-parse HEAD")
    commit_hash = stdout.strip() if not stderr else "master"

    await ctx.respond(f"<{base_url}/blob/{commit_hash}/{blob}{hash_jump}>")


@initializer
def extension_initializer(handler: GatewayCommandHandler) -> None:
    handler.set_data(psutil.Process())
    handler.add_command(ping)
    handler.add_command(stats)
    handler.add_command(source)


@finalizer
def extension_finalizer(handler: GatewayCommandHandler) -> None:
    handler._data.pop(psutil.Process)
    handler.remove_command(ping)
    handler.remove_command(stats)
    handler.remove_command(source)
