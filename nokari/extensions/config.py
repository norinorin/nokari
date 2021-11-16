import typing

import hikari
import lightbulb
from hikari.snowflakes import Snowflake
from lightbulb import errors
from lightbulb.checks import has_role_permissions
from lightbulb.cooldowns import UserBucket

from nokari import core
from nokari.utils import db, plural


class Prefixes(db.Table):
    hash: db.PrimaryKeyColumn[Snowflake]
    prefixes: db.Column[typing.List[str]]


class PrefixConverter(lightbulb.converters.BaseConverter[str]):
    __slots__ = ()

    async def convert(self, arg: str) -> str:
        if (me := self.context.bot.get_me()) and arg in (
            f"<@{me.id}>",
            f"<@!{me.id}>",
        ):
            raise errors.ConverterFailure(f"{arg} is an existing prefix...")

        return arg.strip().lower()


config = core.Plugin("Config")

PREFIX_TOGGLE_QUERY: str = """
    INSERT INTO prefixes (hash, prefixes) VALUES ($1, ARRAY[$2])
    ON CONFLICT(hash)
    DO UPDATE
        SET prefixes = CASE WHEN prefixes.prefixes @> ARRAY[$2]
                THEN array_remove(prefixes.prefixes, $2)
            ELSE prefixes.prefixes[cardinality(prefixes.prefixes)-8:] || $2 END
        WHERE prefixes.hash = $1
"""


def format_prefixes(prefixes: typing.Sequence[str]) -> typing.List[str]:
    zws = "\u200b"
    return [f"`{prefix or zws}`" for prefix in prefixes]


@config.command
@core.add_cooldown(4, 1, UserBucket)
@core.command("prefix", "Shows the usable prefixes.")
@core.implements(lightbulb.commands.PrefixCommandGroup)
async def prefix(ctx: core.Context) -> None:
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
    prefixes = (
        {
            record["hash"]: record["prefixes"]
            for record in await ctx.bot.pool.fetch(query, [ctx.guild_id, ctx.author.id])
        }
        if ctx.bot.pool
        else {}
    )

    cache = getattr(ctx.bot, "prefixes", {})
    cache.update(prefixes)

    if not prefixes.get(ctx.guild_id):
        cache.pop(ctx.guild_id, None)
        prefixes[ctx.guild_id] = ctx.bot.default_prefixes

    embed = hikari.Embed(
        title="Prefixes",
        description=f"**{ctx.get_guild().name}**: {', '.join(format_prefixes(prefixes[ctx.guild_id]))}",
    )

    if prefixes.get(ctx.author.id):
        embed.description = (
            f"{embed.description}\n**{ctx.author}**: "
            f"{', '.join(format_prefixes(prefixes[ctx.author.id]))}"
        )
    else:
        cache.pop(ctx.author.id, None)

    await ctx.respond(embed=embed)


@prefix.child
@core.add_cooldown(4, 1, UserBucket)
@core.consume_rest_option(
    "prefix", "The prefix to toggle.", PrefixConverter, default=""
)
@core.command(
    "user", "Appends the prefix to user prefixes if not exists, otherwise remove it."
)
@core.implements(lightbulb.commands.PrefixSubCommand)
async def prefix_user(ctx: core.Context) -> None:
    await ctx.bot.pool.execute(PREFIX_TOGGLE_QUERY, ctx.author.id, ctx.options.prefix)
    await prefix.callback(ctx)


@prefix.child
@core.add_cooldown(4, 1, UserBucket)
@core.add_checks(has_role_permissions(hikari.Permissions.MANAGE_MESSAGES))
@core.consume_rest_option(
    "prefix", "The prefix to toggle.", PrefixConverter, default=""
)
@core.command(
    "guild",
    "Appends the prefix to guild prefixes if not exists, otherwise remove it.",
    required_vars=["POSTGRESQL_DSN"],
)
@core.implements(lightbulb.commands.PrefixSubCommand)
async def prefix_guild(ctx: core.Context) -> None:
    """
    Appends the prefix to guild prefixes if not exists, otherwise remove it.
    The default prefixes are only available if there are no guild prefixes were set.
    """
    await ctx.bot.pool.execute(PREFIX_TOGGLE_QUERY, ctx.guild_id, ctx.options.prefix)
    await prefix.callback(ctx)


@prefix.child
@core.add_cooldown(4, 1, UserBucket)
@core.command("cache", "Displays the prefix cache.", required_vars=["POSTGRESQL_DSN"])
@core.implements(lightbulb.commands.PrefixSubCommand)
async def prefix_cache(ctx: core.Context) -> None:
    """Displays the prefix cache."""
    get = ctx.bot.prefixes.get
    not_cached = "No cached prefixes..."
    embed = (
        hikari.Embed(title="Prefix Cache")
        .add_field(name="Global", value=f"{plural(len(ctx.bot.prefixes)):hash|hashes,}")
        .add_field(
            name="Guild",
            value=", ".join(format_prefixes(get(ctx.guild_id, []))) or not_cached,
        )
        .add_field(
            name="User",
            value=", ".join(format_prefixes(get(ctx.author.id, []))) or not_cached,
        )
    )

    await ctx.respond(embed=embed)


def load(bot: core.Nokari) -> None:
    bot.add_plugin(config)


def unload(bot: core.Nokari) -> None:
    bot.remove_plugin("Config")
