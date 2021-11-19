import inspect
import os
import sys
import time
from collections import Counter

import hikari
import lightbulb
import psutil

from nokari import core
from nokari.core import Context
from nokari.extensions.extras.admin import run_command_in_shell
from nokari.utils import converters, human_timedelta, paginator, parser, plural, spotify

meta = core.Plugin("Meta")
PROCESS = psutil.Process()


# pylint: disable=too-many-locals
def get_info(ctx: core.Context, embed: hikari.Embed, owner: bool = False) -> None:
    """Modifies the embed to contain the statistics."""
    total_members = sum(
        [g.member_count for g in ctx.bot.cache.get_available_guilds_view().values()]
    )
    channels = (
        "\n".join(
            f"{v} {str(k).split('_', 2)[-1].lower()}"
            for k, v in Counter(
                [c.type for c in ctx.bot.cache.get_guild_channels_view().values()]
            ).items()
        )
        or "No cached channels..."
    )
    presences = sum([len(i) for i in ctx.bot.cache.get_presences_view().values()])
    counter = Counter(
        [
            m.is_bot
            for mapping in ctx.bot.cache.get_members_view().values()
            for m in mapping.values()
        ]
    )
    bots, human = counter[True], counter[False]
    boot_time = human_timedelta(
        psutil.boot_time(),
        append_suffix=False,
        brief=True,
    )
    total_servers = len(ctx.bot.cache.get_available_guilds_view()) + len(
        ctx.bot.cache.get_unavailable_guilds_view()
    )
    (
        embed.add_field(
            name="Uptime:",
            value=f"Bot: {ctx.bot.brief_uptime}\nServer: {boot_time}",
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
                f"({len(ctx.bot.cache._presences_garbage):,} unique)\n"
                f"{plural(len(converters._member_cache)):converted member,}"
            ),
            inline=True,
        )
        .add_field(
            name="CPU:",
            value=f"{round(PROCESS.cpu_percent()/psutil.cpu_count(), 2)}%",
            inline=True,
        )
    )

    memory_full_info = PROCESS.memory_full_info()
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


@meta.command
@core.add_cooldown(10, 1, lightbulb.cooldowns.UserBucket)
@core.command("ping", "Displays the latencies.", aliases=["pong", "latency"])
@core.implements(lightbulb.commands.PrefixCommand)
async def ping(ctx: Context) -> None:
    embed = (
        hikari.Embed()
        .set_author(name="Ping", icon=ctx.bot.get_me().avatar_url)
        .add_field("WS heartbeat latency", _format_latency(ctx.bot.heartbeat_latency))
    )

    t0 = time.perf_counter()
    resp = await (await ctx.respond(embed=embed)).message()
    rest_latency = time.perf_counter() - t0
    embed.add_field("REST latency", _format_latency(rest_latency))
    await resp.edit(embed=embed)


@meta.command
@core.add_cooldown(10, 1, lightbulb.cooldowns.UserBucket)
@core.option("flags", "", default="")
@core.command("stats", "Displays the statistic of the bot.")
@core.implements(lightbulb.commands.PrefixCommand)
async def stats(ctx: Context) -> None:
    """Displays the statistic of the bot."""
    embed = hikari.Embed(title="Stats")
    get_info(
        ctx,
        embed,
        owner="d" in ctx.options.flags.lower() and ctx.author.id in ctx.bot.owner_ids,
    )
    await ctx.respond(embed=embed)


@meta.command
@core.add_cooldown(2, 1, lightbulb.cooldowns.UserBucket)
@core.option("object", "The object query.", default=None)
@core.command("source", "Returns the link to the source code.")
@core.implements(lightbulb.commands.PrefixCommand)
async def source(ctx: Context) -> None:
    """
    Returns the link to the specified object if exists.
    """
    base_url = "https://github.com/norinorin/nokari"

    if ctx.options.object is None:
        await ctx.respond(base_url)
        return

    obj_map = {
        "help": ctx.bot.help_command.__class__,
        "bot": ctx.bot.__class__,
        "context": ctx.__class__,
        "cache": ctx.bot.cache.__class__,
        "spotify": spotify.SpotifyClient,
        "paginator": paginator.Paginator,
        "parser": parser.ArgumentParser,
    }

    aliases = {"sp": "spotify", "ctx": "context"}

    obj = ctx.options.object.lower()

    maybe_command = obj_map.get(aliases.get(obj, obj), ctx.bot.get_prefix_command(obj))
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


def load(bot: core.Nokari) -> None:
    bot.add_plugin(meta)


def unload(bot: core.Nokari) -> None:
    bot.remove_plugin("Meta")
