import typing

import hikari
from hikari.snowflakes import Snowflake
from lightbulb import Bot, errors, plugins
from lightbulb.converters import WrappedArg
from lightbulb.cooldowns import UserBucket

from nokari import core
from nokari.core import cooldown
from nokari.utils import db, plural


class Prefixes(db.Table):
    hash: db.PrimaryKeyColumn[Snowflake]
    prefixes: db.Column[typing.List[str]]


def convert_prefix(arg: WrappedArg) -> str:
    bot = arg.context.bot
    if arg.data in (f"<@{bot.me.id}>", f"<@!{bot.me.id}>"):
        raise errors.ConverterFailure(f"{arg.data} is an existing prefix...")

    return arg.data.strip().lower()


class Config(plugins.Plugin):
    """A plugin that contains config commands"""

    PREFIX_TOGGLE_QUERY: typing.ClassVar[
        str
    ] = """
        INSERT INTO prefixes (hash, prefixes) VALUES ($1, ARRAY[$2])
        ON CONFLICT(hash)
        DO UPDATE
            SET prefixes = CASE WHEN prefixes.prefixes @> ARRAY[$2]
                THEN array_remove(prefixes.prefixes, $2)
                ELSE prefixes.prefixes || $2 END
            WHERE prefixes.hash = $1
    """

    def __init__(self, bot: Bot) -> None:
        super().__init__()
        self.bot = bot

    @staticmethod
    def format_prefixes(prefixes: typing.Sequence[str]) -> typing.List[str]:
        zws = "\u200b"
        return [f"`{prefix or zws}`" for prefix in prefixes]

    @cooldown(4, 1, UserBucket)
    @core.commands.group()
    async def prefix(self, ctx: core.Context) -> None:
        """Shows the usable prefixes."""
        query = """
        WITH _ as(
            DELETE
                FROM prefixes
                WHERE array_length(prefixes, 1) IS NULL
                AND hash = ANY($1)
        ),
        PREFIXES AS(
            SELECT hash, prefixes
                FROM prefixes
                WHERE hash = ANY($1)
        )
        SELECT hash, prefixes FROM PREFIXES
        """
        prefix = {
            record["hash"]: record["prefixes"]
            for record in await self.bot.pool.fetch(
                query, [ctx.guild_id, ctx.author.id]
            )
        }

        self.bot.prefixes.update(prefix)

        if not prefix.get(ctx.guild_id):
            self.bot.prefixes.pop(ctx.guild_id, None)
            prefix[ctx.guild_id] = self.bot.default_prefix

        embed = hikari.Embed(
            title="Prefixes",
            description=f"**{ctx.guild.name}**: {', '.join(self.format_prefixes(prefix[ctx.guild_id]))}",
        )

        if prefix.get(ctx.author.id):
            embed.description = (
                f"{embed.description}\n**{ctx.author}**: "
                f"{', '.join(self.format_prefixes(prefix[ctx.author.id]))}"
            )
        else:
            self.bot.prefixes.pop(ctx.author.id, None)

        await ctx.respond(embed=embed)

    @cooldown(4, 1, UserBucket)
    @prefix.command(name="user")
    async def prefix_user(self, ctx: core.Context, *args: str) -> None:
        """Appends the prefix to user prefixes if not exists, otherwise it'll be removed."""
        prefix = convert_prefix(WrappedArg(" ".join(typing.cast(str, args)), ctx))
        await self.bot.pool.execute(self.PREFIX_TOGGLE_QUERY, ctx.author.id, prefix)
        await self.prefix.callback(self, ctx)

    @cooldown(4, 1, UserBucket)
    @prefix.command(name="guild")
    async def prefix_guild(self, ctx: core.Context, *args: str) -> None:
        """
        Appends the prefix to guild prefixes if not exists, otherwise, it'll be removed.
        The default prefixes are only available if there are no guild prefixes were set.
        """
        prefix = convert_prefix(WrappedArg(" ".join(typing.cast(str, args)), ctx))
        await self.bot.pool.execute(self.PREFIX_TOGGLE_QUERY, ctx.guild_id, prefix)
        await self.prefix.callback(self, ctx)

    @cooldown(4, 1, UserBucket)
    @prefix.command(name="cache")
    async def prefix_cache(self, ctx: core.Context) -> None:
        """Displays the prefix cache."""
        get = self.bot.prefixes.get
        not_cached = "No cached prefixes..."
        embed = (
            hikari.Embed(title="Prefix Cache")
            .add_field(
                name="Global", value=f"{plural(len(self.bot.prefixes)):hash|hashes}"
            )
            .add_field(
                name="Guild",
                value=", ".join(self.format_prefixes(get(ctx.guild_id, [])))
                or not_cached,
            )
            .add_field(
                name="User",
                value=", ".join(self.format_prefixes(get(ctx.author.id, [])))
                or not_cached,
            )
        )

        await ctx.respond(embed=embed)


def load(bot: Bot) -> None:
    bot.add_plugin(Config(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Config")
