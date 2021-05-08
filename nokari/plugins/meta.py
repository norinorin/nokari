import datetime
from collections import Counter

import hikari
import lightbulb
import psutil
from lightbulb import Bot, plugins

from nokari import core
from nokari.core import Context, cooldown
from nokari.utils import human_timedelta, plural


class Meta(plugins.Plugin):
    """
    A Plugin with commands that show the metadata related to the bot.
    """

    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot
        self.process = psutil.Process()

    def get_info(self, embed: hikari.Embed, owner: bool = False) -> None:
        """Modify the embed to contain the statistics."""
        total_members = sum(
            g.member_count
            for g in self.bot.cache.get_available_guilds_view().iterator()
        )
        channels = "\n".join(
            f"{v} {str(k).split('_', 2)[-1].lower()}"
            for k, v in Counter(
                c.type for c in self.bot.cache.get_guild_channels_view().iterator()
            ).items()
        )
        presences = sum(len(i) for i in self.bot.cache.get_presences_view().iterator())
        counter = Counter(
            [
                m.is_bot
                for mapping in self.bot.cache.get_members_view().iterator()
                for m in mapping.iterator()
            ]
        )
        bots, human = counter[True], counter[False]
        boot_time = human_timedelta(
            datetime.datetime.utcfromtimestamp(psutil.boot_time()),
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
                    f"{plural(presences):presence}"
                ),
                inline=True,
            )
        )

        embed.add_field(
            name="Cpu:",
            value=f"{self.process.cpu_percent()/psutil.cpu_count()}%",
            inline=True,
        )

        memory_full_info = self.process.memory_full_info()
        if not owner:
            name = "Memory:"
            value = f"{round(memory_full_info.uss / 1024** 2, 2)}MiB"
        else:
            name = "RSS / USS:"
            value = (
                f"{round(memory_full_info.rss / 1024 ** 2, 2)}MiB "
                f"/ {round(memory_full_info.uss / 1024** 2, 2)}MiB"
            )

        embed.add_field(name=name, value=value, inline=True)

    @cooldown(10, 1, lightbulb.cooldowns.UserBucket)
    @core.commands.command(aliases=["pong", "latency"])
    async def ping(self, ctx: Context) -> None:
        """Shows the WebSocket latency to the Discord gateway"""
        latency = int(ctx.bot.heartbeat_latency * 1000)
        emoji = "🔴" if latency > 500 else "🟡" if latency > 100 else "🟢"
        await ctx.respond(f"Pong? {emoji} {latency}ms")

    @cooldown(10, 1, lightbulb.cooldowns.UserBucket)
    @core.commands.command()
    async def stats(self, ctx: Context, flags: str = "") -> None:
        """Shows the statistic of the bot."""
        embed = hikari.Embed(title="Stats")
        self.get_info(
            embed, owner="d" in flags.lower() and ctx.author_id in self.bot.owner_ids
        )
        await ctx.respond(embed=embed)


def load(bot: Bot) -> None:
    bot.add_plugin(Meta(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Meta")
