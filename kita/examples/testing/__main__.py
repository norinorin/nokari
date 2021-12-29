import asyncio
import typing as t

import hikari
import psutil
from hikari.commands import OptionType
from hikari.snowflakes import Snowflake

import kita
from kita.contexts import Context
from kita.data import data
from kita.options import with_option
from kita.responses import defer, edit

bot = hikari.GatewayBot("TOKEN", logs="DEBUG")
handler = kita.GatewayCommandHandler(bot, guild_ids={1234}).set_data(psutil.Process())


@handler.command("sub", "Test command")
def sub() -> None:
    ...


@sub.command("command", "Test subcommand")
def sub_command() -> t.Iterator[t.Any]:  # generator
    yield defer()
    yield asyncio.sleep(5)
    yield edit("test")


@sub.group("group", "Test subcommand group")
def sub_group() -> None:
    ...


@sub_group.command("command", "Test subcommand of subcommand group")
@with_option(OptionType.BOOLEAN, "boolean", description="Boolean")
@with_option(OptionType.USER, "user", description="User")
async def sub_group_command(  # async function
    boolean: bool,  # required
    ctx: Context = data(Context),  # context could be injected
    user: t.Optional[Snowflake] = None,  # not required
) -> None:
    await ctx.respond(f"{user}, {boolean}")


for name in "events", "common", "checks", "cooldowns":  # load extensions
    handler.load_extension(f"testing.extensions.{name}")

bot.run()
