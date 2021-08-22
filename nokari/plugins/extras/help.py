import datetime
import inspect
import typing
from operator import attrgetter

import hikari
from lightbulb import Bot, commands
from lightbulb import context as context_
from lightbulb import converters, errors
from lightbulb import help as help_
from lightbulb import plugins

from nokari import core
from nokari.core import Context
from nokari.utils import plural


@core.commands.command(
    name="help", aliases=["commands", "command"], usage="[category|command|query]"
)
async def _help_cmd(ctx: Context) -> None:
    """
    Displays help for the bot, a command, or a category.
    If no object is specified with the command then a help menu
    for the bot as a whole is displayed instead.
    """
    obj = ctx.message.content[len(f"{ctx.prefix}{ctx.invoked_with}") :].strip().split()
    await ctx.bot.help_command.resolve_help_obj(ctx, obj)


class CustomHelp(help_.HelpCommand):
    @staticmethod
    def get_prefix(context: Context) -> str:
        """
        Returns the cleaned prefix if it's no longer than 10 chars,
        otherwise returns the clean mention of the bot itself.
        """
        prefix = context.clean_prefix.strip()
        if len(prefix) > 10:
            prefix = f"@{context.bot.get_me().username}"  # type: ignore

        return f"{prefix} "

    @staticmethod
    def get_base_embed(context: Context) -> hikari.Embed:
        """Returns the base help Embed."""
        embed = hikari.Embed(
            timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
            color=context.color,
        ).set_footer(
            text="For more information, do help <command>",
            icon=context.bot.get_me().avatar_url,  # type: ignore
        )
        return embed

    @staticmethod
    def is_consume_rest_converter(
        converter: converters._BaseConverter,
    ) -> bool:
        while 1:
            if isinstance(converter, converters._ConsumeRestConverter):
                return True

            if not (converter := getattr(converter, "converter", None)):
                break

        return False

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

        items = [fmt]

        if usage := getattr(command, "usage", None):
            items.append(usage)
        else:
            for argname, converter in zip(
                command.arg_details.arguments, command.arg_details.converters
            ):
                if isinstance(converter, converters._Converter) and issubclass(
                    converter.conversion_func, context_.Context
                ):
                    continue

                if isinstance(converter, converters._DefaultingConverter):
                    items.append(f"[{argname}={converter.default!r}]")
                else:
                    items.append(f"<{argname}>")

                if CustomHelp.is_consume_rest_converter(converter):
                    break

        return " ".join(items)

    @staticmethod
    async def send_help_overview(context: Context) -> None:
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
            value="[Invite](https://discord.com/oauth2/authorize?client_id=7250819253115290"
            "31&permissions=1609953143&scope=bot 'Click this to invite me') | [Vote](https:"
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

        entries = await help_.filter_commands(context, plugin._commands.values())
        command_names = sorted(
            [f"`{cmd.qualified_name}`" for cmd in entries],
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
        if not isinstance(command, commands.Group):
            embed.footer.text = "Got confused? Be sure to join the support server!"  # type: ignore

    @staticmethod
    async def send_command_help(context: Context, command: commands.Command) -> None:
        try:
            await command.is_runnable(context)
        except errors.CheckFailure:
            await CustomHelp.object_not_found(context, "")
            return

        embed = CustomHelp.get_base_embed(context)
        CustomHelp.common_command_formatting(context, embed, command)
        await context.respond(embed=embed)

    @staticmethod
    async def send_group_help(context: Context, group: commands.Group) -> None:
        try:
            await group.is_runnable(context)
        except errors.CheckFailure:
            await CustomHelp.object_not_found(context, "")
            return

        if not (subcommands := await help_.filter_commands(context, group.subcommands)):
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

        cmd = context.bot.get_command(query)

        iterable = getattr(cmd, "subcommands", context.bot.commands)

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
            if i in a.__class__.__name__.lower()
        ]

        if len(matched_plugins) == 1:  # To make plugin queries case-insensitive
            return await CustomHelp.send_plugin_help(context, matched_plugins[0])

        # todo: fuzzy string matching
        matches = sum(
            [
                x
                for x in [
                    [
                        c
                        for i in queries
                        if i
                        in (
                            fmt(c)
                            if not isinstance(c, commands.Group)
                            else "".join(fmt(cmd) for cmd in c.subcommands)
                        )
                    ]
                    for c in await help_.filter_commands(context, iterable)
                ]
                if x
            ],
            [],
        )

        if len(matches) == 1:  # Just send the object if there's only 1 result
            return await context.send_help(matches[0])

        matches = [c.qualified_name for c in matches]
        matches.extend([i.__class__.__name__ for i in matched_plugins])
        matches.sort(key=lambda x: (x, len(x)))
        matches = {f"`{i}`" for i in matches}
        embed = CustomHelp.get_base_embed(context)
        embed.title = f'{plural(len(matches)):result,} on "{query}"'
        embed.description = ", ".join(matches) or "Oops, seems there's nothing found"
        return embed

    @staticmethod
    def get_arg(context: Context) -> str:
        return context.message.content[
            len(f"{context.prefix}{context.invoked_with}") :
        ].strip()

    @staticmethod
    async def object_not_found(context: Context, _: str) -> None:
        embed = await CustomHelp.query(context)

        if embed is None:
            return

        await context.respond(embed=embed)


class Help(plugins.Plugin):
    """
    A plugin that overrides the default help command.
    """

    def __init__(self, bot: Bot) -> None:
        super().__init__()
        self.bot = bot
        self.old_help_command = bot.help_command
        bot.help_command = CustomHelp(bot)
        bot.remove_command("help")
        bot.add_command(_help_cmd)

    def plugin_remove(self) -> None:
        self.bot.help_command = self.old_help_command
        self.bot.remove_command("help")
        self.bot.add_command(help_._help_cmd)


def load(bot: Bot) -> None:
    bot.add_plugin(Help(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Help")
