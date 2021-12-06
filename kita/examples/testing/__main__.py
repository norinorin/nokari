import asyncio
import typing as t

import hikari
from hikari.commands import OptionType
from hikari.interactions.base_interactions import ResponseType
from hikari.interactions.command_interactions import CommandInteraction
from hikari.snowflakes import Snowflake

import kita
from kita.data import data
from kita.options import with_option
from kita.responses import edit, respond

bot = hikari.GatewayBot("TOKEN", logs="DEBUG")
handler = kita.GatewayCommandHandler(bot, guild_ids={726291069976969329})


@handler.command("base", "Base command")
def base() -> None:
    ...


@base.command("subcommand", "Test subcommand")
def base_subcommand() -> t.Iterator[t.Any]:  # generator
    yield respond(ResponseType.DEFERRED_MESSAGE_CREATE)
    yield asyncio.sleep(5)
    yield edit("test")


@base.group("subgroup", "Test subcommand group")
def base_subgroup() -> None:
    ...


@base_subgroup.command("subcommand", "Test subcommand of subcommand group")
@with_option(OptionType.BOOLEAN, "boolean", description="Boolean")
@with_option(OptionType.USER, "user", description="User")
async def base_subgroup_subcommand(  # async function
    boolean: bool,  # required
    user: t.Optional[Snowflake] = None,  # not required
    interaction: CommandInteraction = data(CommandInteraction),
) -> None:
    await interaction.create_initial_response(
        ResponseType.MESSAGE_CREATE, f"{boolean}\n{user}"
    )


for name in "events", "ping":  # load extensions
    handler.load_extension(f"testing.extensions.{name}")

bot.run()
