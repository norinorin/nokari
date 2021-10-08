import datetime
import inspect
import os
import sys
import time
import typing
from collections import Counter

import hikari
import lightbulb
import psutil
from lightbulb import Bot, plugins

from nokari import core
from nokari.core import Context, cooldown
from nokari.utils import converters, human_timedelta, paginator, parser, plural, spotify


class Meta(plugins.Plugin):
    """
    A Plugin with commands that show the metadata related to the bot.
    """

    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot
        self.process = psutil.Process()

    # pylint: disable=too-many-locals
    def get_info(self, embed: hikari.Embed, owner: bool = False) -> None:
        """Modifies the embed to contain the statistics."""
        total_members = sum(
            [
                g.member_count
                for g in self.bot.cache.get_available_guilds_view().values()
            ]
        )
        channels = (
            "\n".join(
                f"{v} {str(k).split('_', 2)[-1].lower()}"
                for k, v in Counter(
                    [c.type for c in self.bot.cache.get_guild_channels_view().values()]
                ).items()
            )
            or "No cached channels..."
        )
        presences = sum([len(i) for i in self.bot.cache.get_presences_view().values()])
        counter = Counter(
            [
                m.is_bot
                for mapping in self.bot.cache.get_members_view().values()
                for m in mapping.values()
            ]
        )
        bots, human = counter[True], counter[False]
        boot_time = human_timedelta(
            psutil.boot_time(),
            append_suffix=False,
            brief=True,
        )
        total_servers = len(self.bot.cache.get_available_guilds_view()) + len(
            self.bot.cache.get_unavailable_guilds_view()
        )
        (
            embed.add_field(
                name="Uptime:",
                value=f"Bot: {self.bot.brief_uptime}\nServer: {boot_time}",
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
                    f"({len(self.bot.cache._presences_garbage):,} unique)\n"
                    f"{plural(len(converters._member_cache)):converted member,}"
                ),
                inline=True,
            )
            .add_field(
                name="CPU:",
                value=f"{round(self.process.cpu_percent()/psutil.cpu_count(), 2)}%",
                inline=True,
            )
        )

        memory_full_info = self.process.memory_full_info()
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

    @cooldown(10, 1, lightbulb.cooldowns.UserBucket)
    @core.commands.command(aliases=["pong", "latency"])
    async def ping(self, ctx: Context) -> None:
        """Displays the WebSocket latency to the Discord gateway."""

        def format_latency(latency):
            emoji = (
                "🔴"
                if (latency := int(latency * 1000)) > 500
                else "🟡"
                if latency > 100
                else "🟢"
            )
            return f"{emoji} `{latency} ms`"

        embed = (
            hikari.Embed(title="Ping")
            .set_author(icon=self.bot.get_me().avatar_url)
            .add_field(
                "WS heartbeat latency", format_latency(self.bot.heartbeat_latency)
            )
        )

        t0 = time.perf_counter()
        msg = await ctx.respond(embed=embed)
        rest_latency = time.perf_counter() - t0
        embed.add_field("REST latency", format_latency(rest_latency))
        await msg.edit(embed=embed)

    @cooldown(10, 1, lightbulb.cooldowns.UserBucket)
    @core.commands.command()
    async def stats(self, ctx: Context, flags: str = "") -> None:
        """Displays the statistic of the bot."""
        embed = hikari.Embed(title="Stats")
        self.get_info(
            embed, owner="d" in flags.lower() and ctx.author.id in self.bot.owner_ids
        )
        await ctx.respond(embed=embed)

    @cooldown(2, 1, lightbulb.cooldowns.UserBucket)
    @core.commands.command(usage="[command|object]")
    async def source(self, ctx: Context, *, obj: typing.Optional[str] = None) -> None:
        """
        Returns the link to the specified object if exists.
        """
        base_url = "https://github.com/norinorin/nokari"

        if obj is None:
            await ctx.respond(base_url)
            return

        obj_map = {
            "help": self.bot.help_command.__class__,
            "bot": self.bot.__class__,
            "context": ctx.__class__,
            "cache": self.bot.cache.__class__,
            "spotify": spotify.SpotifyClient,
            "paginator": paginator.Paginator,
            "parser": parser.ArgumentParser,
        }

        aliases = {"sp": "spotify", "ctx": "context"}

        obj = obj.lower()

        maybe_command = obj_map.get(aliases.get(obj, obj), self.bot.get_command(obj))
        if maybe_command is None:
            await ctx.respond("Couldn't find anything...")
            return

        actual_obj = getattr(maybe_command, "callback", maybe_command)

        lines, lineno = inspect.getsourcelines(actual_obj)
        hash_jump = f"#L{lineno}-L{lineno+len(lines)-1}"
        blob = os.path.relpath(sys.modules[actual_obj.__module__].__file__)

        admin = self.bot.get_plugin("Admin")
        stdout, stderr = await admin.run_command_in_shell("git rev-parse HEAD")
        commit_hash = stdout.strip() if not stderr else "master"

        await ctx.respond(f"<{base_url}/blob/{commit_hash}/{blob}{hash_jump}>")


def load(bot: Bot) -> None:
    bot.add_plugin(Meta(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Meta")
