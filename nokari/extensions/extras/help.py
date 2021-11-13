import datetime
import inspect
import typing
from operator import attrgetter

import hikari
import lightbulb
from lightbulb import BotApp, commands, help_command, plugins

from nokari import core
from nokari.core import Context
from nokari.utils import plural


@core.consume_rest_option("object", "Object to get help for.", required=False)
@core.command(
    "help",
    "Get information about the bot.",
    signature="[category|command|query]",
)
@core.implements(lightbulb.commands.PrefixCommand)
async def _help_cmd(ctx: Context) -> None:
    """
    Displays help for the bot, a command, or a category.
    If no object is specified with the command then a help menu
    for the bot as a whole is displayed instead.
    """
    await ctx.bot._help_command.send_help(ctx, ctx.options.object)


class CustomHelp(help_command.DefaultHelpCommand):
    @staticmethod
    def get_prefix(context: Context) -> str:
        """
        Returns the cleaned prefix if it's no longer than 10 chars,
        otherwise returns the clean mention of the bot itself.
        """
        prefix = context.prefix.strip()
        if len(prefix) > 10:
            prefix = f"@{context.bot.get_me().username}"

        return f"{prefix} "

    @staticmethod
    def get_base_embed(context: Context) -> hikari.Embed:
        """Returns the base help Embed."""
        embed = hikari.Embed(
            timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
            color=context.color,
        ).set_footer(
            text="For more information, do help <command>",
            icon=context.bot.get_me().avatar_url,
        )
        return embed

    @staticmethod
    def get_command_signature(command: commands.Command) -> str:
        """
        Gets the command signature for a command or a command group.
        """

        parent = command.parent
        if len(command.aliases) > 0:
            aliases = "|".join(command.aliases)
            fmt = f"[{command.name}|{aliases}]"
            if parent:
                fmt = f"{parent.name} {fmt}"
        else:
            fmt = command.name if not parent else f"{parent.name} {command.name}"

        return (
            fmt + " " + getattr(command._initialiser, "signature", None)
            or command.signature
        )

    @staticmethod
    async def send_bot_help(context: Context) -> None:
        zws = "\u200b"
        invoked_with = context.invoked_with
        prefix = CustomHelp.get_prefix(context)
        embed = CustomHelp.get_base_embed(context)
        embed.title = "Category List"
        embed.description = (
            f"This is the help command, you could either do `{prefix}{invoked_with} [category]`"
            f" to get list of commands of a category or `{prefix}{invoked_with} [command]` "
            "to get more information about a command or"
            f"`{prefix}{invoked_with} [query]` to search commands.\n\n"
            "Everything that wrapped inside: \n- `[]` is optional\n- `<>` is required\n"
            "Bear in mind that you're not supposed to pass the `[]` and `<>`\n\n"
            "This is an open-source project, stars are greatly appreciated!\n\n"
        )

        embed.footer.text = "For more information, do help <category>"  # type: ignore

        for name, plugin in context.bot.plugins.items():
            if plugin.__module__.startswith("nokari.plugins.extras."):
                continue

            embed.add_field(
                name=name,
                value=f"```{prefix.replace('`', zws+'`')}{invoked_with} {name}```",
                inline=True,
            )

        embed.add_field(
            name="Links:",
            value=f"[Invite](https://discord.com/oauth2/authorize?client_id={context.me.id}"
            "&permissions=1609953143&scope=bot 'Click this to invite me') | [Vote](https:"
            "//top.gg/bot/725081925311529031/vote 'Click this to vote me') | [Support Server]"
            "(https://discord.com/invite/4KPMCum 'Click this to join the support server!')",
            inline=False,
        )

        await context.respond(embed=embed)

    @staticmethod
    async def send_plugin_help(context: Context, plugin: plugins.Plugin) -> None:
        if (
            plugin.__module__.startswith("nokari.plugins.extras.")
            and context.author.id not in context.bot.owner_ids
        ):
            return await CustomHelp.object_not_found(context, "")

        entries = await help_command.filter_commands(plugin._all_commands, context)
        command_names = sorted(
            [f"`{cmd.name}`" for cmd in entries],
            key=lambda s: (s.strip("`"), len(s)),
        )

        help_text = (
            f"{', '.join(command_names)}"
            if command_names
            else "You lack permissions to run any command in this category"
        )

        embed = CustomHelp.get_base_embed(context)
        embed.title = f"{plugin.name} Commands"
        embed.description = help_text
        await context.respond(embed=embed)

    @staticmethod
    def common_command_formatting(
        context: Context, embed: hikari.Embed, command: commands.Command
    ) -> None:
        embed.title = CustomHelp.get_command_signature(command)
        embed.description = inspect.getdoc(command.callback) or "No help found..."
        if not isinstance(command, commands.PrefixGroupMixin):
            embed.footer.text = "Got confused? Be sure to join the support server!"  # type: ignore

    @staticmethod
    async def send_command_help(context: Context, command: commands.Command) -> None:
        # TODO
        # try:
        #     await command.is_runnable(context)
        # except errors.CheckFailure:
        #     await CustomHelp.object_not_found(context, "")
        #     return

        embed = CustomHelp.get_base_embed(context)
        CustomHelp.common_command_formatting(context, embed, command)
        await context.respond(embed=embed)

    @staticmethod
    async def send_group_help(
        context: Context, group: commands.PrefixGroupMixin
    ) -> None:
        # TODO
        # try:
        #     await group.is_runnable(context)
        # except errors.CheckFailure:
        #     await CustomHelp.object_not_found(context, "")
        #     return

        if not (
            subcommands := await help_command.filter_commands(
                group._subcommands.values(), context
            )
        ):
            return await CustomHelp.send_command_help(context, group)

        embed = CustomHelp.get_base_embed(context)
        CustomHelp.common_command_formatting(context, embed, group)

        for subcommand in sorted(subcommands, key=attrgetter("name")):
            embed.add_field(
                name=CustomHelp.get_command_signature(subcommand),
                value=inspect.getdoc(subcommand.callback) or "No help text provided...",
                inline=False,
            )

        await context.respond(embed=embed)

    @staticmethod
    async def query(context: Context) -> typing.Optional[hikari.Embed]:
        query = CustomHelp.get_arg(context)
        queries = [i.lower() for i in query.split()]

        cmd = context.bot.get_prefix_command(query)

        iterable = getattr(cmd, "_subcommands", context.bot._prefix_commands).values()

        def fmt(c: commands.Command) -> str:
            return f'{c}{"".join(c.aliases)}{inspect.getdoc(c.callback) or ""}'

        matched_plugins = [
            a
            for i in queries
            for a in [
                p
                for p in context.bot.plugins.values()
                if context.author.id in context.bot.owner_ids
                or not p.__module__.startswith("nokari.plugins.extras.")
            ]
            if i in a.name.lower()
        ]

        if len(matched_plugins) == 1:  # To make plugin queries case-insensitive
            return await CustomHelp.send_plugin_help(context, matched_plugins[0])

        # todo: fuzzy string matching
        matches: typing.List[commands.Command] = sum(
            [
                x
                for x in [
                    [
                        c
                        for i in queries
                        if i
                        in (
                            fmt(c)
                            if not isinstance(c, commands.PrefixGroupMixin)
                            else "".join(fmt(cmd) for cmd in c._subcommands.values())
                        )
                    ]
                    for c in await help_command.filter_commands(iterable, context)
                ]
                if x
            ],
            [],
        )

        if len(matches) == 1:  # Just send the object if there's only 1 result
            return await context.send_help(matches[0])

        matches: typing.List[str] = [c.name for c in matches]
        matches.extend([i.__class__.__name__ for i in matched_plugins])
        matches.sort(key=lambda x: (x, len(x)))
        matches = {f"`{i}`" for i in matches}
        embed = CustomHelp.get_base_embed(context)
        embed.title = f'{plural(len(matches)):result,} on "{query}"'
        embed.description = ", ".join(matches) or "Oops, seems there's nothing found"
        return embed

    @staticmethod
    def get_arg(context: Context) -> str:
        return context.event.message.content[
            len(f"{context.prefix}{context.invoked_with}") :
        ].strip()

    @staticmethod
    async def object_not_found(context: Context, _: str) -> None:
        embed = await CustomHelp.query(context)

        if embed is None:
            return

        await context.respond(embed=embed)


old_help_inst: help_command.BaseHelpCommand
old_help_command: lightbulb.commands.CommandLike


def load(bot: BotApp) -> None:
    global old_help_inst, old_help_command
    old_help_inst = bot._help_command
    old_help_command = bot.get_prefix_command("help")._initialiser
    bot._help_command = CustomHelp(bot)
    bot.remove_command(old_help_command)
    bot.command(_help_cmd)


def unload(bot: BotApp) -> None:
    bot.help_command = old_help_command
    bot.remove_command(_help_cmd)
    bot.command(old_help_command)
