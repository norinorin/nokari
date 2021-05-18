import datetime
import inspect
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
            g.member_count
            for g in self.bot.cache.get_available_guilds_view().iterator()
        )
        channels = (
            "\n".join(
                f"{v} {str(k).split('_', 2)[-1].lower()}"
                for k, v in Counter(
                    c.type for c in self.bot.cache.get_guild_channels_view().iterator()
                ).items()
            )
            or "No cached channels..."
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
                    f"{plural(presences):presence}\n"
                    f"{plural(len(converters._member_cache)):converted member}"
                ),
                inline=True,
            )
            .add_field(
                name="Cpu:",
                value=f"{self.process.cpu_percent()/psutil.cpu_count()}%",
                inline=True,
            )
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

        (
            embed.add_field(name=name, value=value, inline=True).add_field(
                name="Cached prefixes",
                value=f"{plural(len(self.bot.prefixes)):hash|hashes}",
                inline=True,
            )
        )

        API = self.bot.get_plugin("API")
        if not API:
            return

        spotify_api_responses_cache = len(
            API.spotify_card_generator.track_from_id_cache
        ) + len(API.spotify_card_generator.track_from_search_cache)

        embed.add_field(
            name="Spotify cache",
            value=f"Albums: {len(API.spotify_card_generator.album_cache)}\n"
            f"Colors: {len(API.spotify_card_generator.color_cache)}\n"
            f"Texts: {len(API.spotify_card_generator.text_cache)}\n"
            f"Spotify track queries: {spotify_api_responses_cache}\n"
            f"Spotify codes: {len(API.spotify_card_generator.code_cache)}",
            inline=True,
        )

    @cooldown(10, 1, lightbulb.cooldowns.UserBucket)
    @core.commands.command(aliases=["pong", "latency"])
    async def ping(self, ctx: Context) -> None:
        """Shows the WebSocket latency to the Discord gateway."""
        latency = int(ctx.bot.heartbeat_latency * 1000)
        emoji = "🔴" if latency > 500 else "🟡" if latency > 100 else "🟢"
        await ctx.respond(f"Pong? {emoji} {latency}ms")

    @cooldown(10, 1, lightbulb.cooldowns.UserBucket)
    @core.commands.command()
    async def stats(self, ctx: Context, flags: str = "") -> None:
        """Shows the statistic of the bot."""
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
            "spotify": spotify.SpotifyCardGenerator,
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
        blob = f"{actual_obj.__module__.replace('.', '/')}.py"

        await ctx.respond(f"<{base_url}/blob/master/{blob}{hash_jump}>")


def load(bot: Bot) -> None:
    bot.add_plugin(Meta(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Meta")
