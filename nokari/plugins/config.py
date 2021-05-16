import typing

import hikari
from hikari.snowflakes import Snowflake
from lightbulb import Bot, errors, plugins
from lightbulb.converters import WrappedArg

from nokari import core
from nokari.utils import db


class Prefixes(db.Table):
    hash: db.PrimaryKeyColumn[Snowflake]
    prefixes: db.Column[typing.List[str]]


def convert_prefix(arg: WrappedArg) -> str:
    bot = arg.context.bot
    if arg.data in (f"<@{bot.me.id}>", f"<@!{bot.me.id}>"):
        raise errors.ConverterFailure(f"{arg.data} is an existing prefix...")

    return arg.data


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

    @core.commands.group()
    async def prefix(self, ctx: core.Context) -> None:
        """Shows the set prefixes"""
        prefix = {
            record["hash"]: record["prefixes"]
            for record in await self.bot.pool.fetch(
                "SELECT * FROM prefixes WHERE hash = $1 or hash = $2;",
                ctx.guild_id,
                ctx.author.id,
            )
        }

        self.bot.prefixes.update(prefix)

        if not prefix.get(ctx.guild_id):
            prefix[ctx.guild_id] = self.bot.default_prefix

        embed = hikari.Embed(title="Prefixes")
        embed.description = f"**{ctx.guild.name}**: {', '.join(self.format_prefixes(prefix[ctx.guild_id]))}"
        if prefix.get(ctx.author.id):
            embed.description += f"\n**{ctx.author}**: {', '.join(self.format_prefixes(prefix[ctx.author.id]))}"

        await ctx.respond(embed=embed)

    @prefix.command(name="user")
    async def prefix_user(self, ctx: core.Context, *args: str) -> None:
        """Append the prefix to user prefixes if not exists, otherwise it'll be removed"""
        prefix = convert_prefix(
            WrappedArg(" ".join(typing.cast(str, args)).lower(), ctx)
        )
        await self.bot.pool.execute(self.PREFIX_TOGGLE_QUERY, ctx.author.id, prefix)
        await self.prefix.callback(self, ctx)

    @prefix.command(name="guild")
    async def prefix_guild(self, ctx: core.Context, *args: str) -> None:
        """Append the prefix to guild prefixes if not exists, otherwise it'll be removed"""
        prefix = convert_prefix(
            WrappedArg(" ".join(typing.cast(str, args)).lower(), ctx)
        )
        await self.bot.pool.execute(self.PREFIX_TOGGLE_QUERY, ctx.guild_id, prefix)
        await self.prefix.callback(self, ctx)


def load(bot: Bot) -> None:
    bot.add_plugin(Config(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Config")
