import datetime
import typing

import hikari
from lightbulb import Bot, commands
from lightbulb import help as help_
from lightbulb import plugins

from nokari.core import Command, Context
from nokari.utils import plural


@commands.command(
    name="help",
    aliases=["commands", "command"],
    usage="[category | command | query]",
    cls=Command,
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
    def get_prefix(self, context: Context) -> str:
        """
        Returns the cleaned prefix if it's no longer than 10 chars,
        otherwise returns the clean mention of the bot itself.
        """
        prefix = context.clean_prefix.strip()
        if len(prefix) > 10:
            prefix = f"@{context.bot.me.username}"

        return f"{prefix} "

    def get_command_description(self, command: Command) -> str:
        """
        Returns the first line of the docstring of the command.
        """
        return help_.get_help_text(command).split("\n")[0] or "No description..."

    def get_embed(self, context: Context) -> hikari.Embed:
        """
        Returns a default help Embed.
        This will not return the same Embed object if called multiple times.
        """
        embed = hikari.Embed(
            timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
            color=context.color,
        ).set_footer(
            text="For more information, do help <command>",
            icon=context.bot.me.avatar_url,
        )
        return embed

    def get_command_signature(self, command: commands.Command) -> str:
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
        return f"{fmt} {command.usage}" if hasattr(command, "usage") else fmt

    async def send_help_overview(self, context: Context) -> None:
        zws = "\u200b"
        help_ = context.invoked_with
        prefix = self.get_prefix(context)
        embed = self.get_embed(context)
        embed.title = "Category List"
        embed.description = (
            f"This is the help command, you could either do `{prefix}{help_} [category]` to get list of commands of a category or `{prefix}{help_} [command]` "
            f"to get more information about a command or `{prefix}{help_} [query]` to search commands.\n\n"
            "Everything that wrapped inside: \n- `[]` is optional\n- `<>` is required\n"
            "Bear in mind that you're not supposed to pass the `[]` and `<>`\n\n"
        )

        embed._footer.text = "For more information, do help <category>"  # type: ignore

        for name, plugin in context.bot.plugins.items():
            if plugin.__module__.startswith("nokari.plugins.extras."):
                continue

            embed.add_field(
                name=name,
                value=f"```{prefix.replace('`', zws+'`')}{help_} {name}```",
                inline=True,
            )

        embed.add_field(
            name="Links:",
            value="[Invite](https://discord.com/oauth2/authorize?client_id=725081925311529031&permissions=1609953143&scope=bot 'Click this to invite me') | [Vote](https://top.gg/bot/725081925311529031/vote 'Click this to vote me') | [Support Server](https://discord.com/invite/4KPMCum 'Click this to join the support server!')",
            inline=False,
        )

        await context.respond(embed=embed)

    async def send_plugin_help(self, context: Context, plugin: plugins.Plugin) -> None:
        if (
            plugin.__module__.startswith("nokari.plugins.extras.")
            and context.author.id not in context.bot.owner_ids
        ):
            return await self.send_error_message(
                await self.object_not_found(context, plugin)
            )

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

        embed = self.get_embed(context)
        embed.title = f"{plugin.name} Commands"
        embed.description = help_text
        await context.respond(embed=embed)

    def common_command_formatting(
        self, context: Context, embed: hikari.Embed, command: commands.Command
    ) -> None:
        embed.title = self.get_command_signature(command)
        embed.description = help_.get_help_text(command) or "No help found..."
        if command.__class__ is commands.Command:
            embed._footer.text = "Got confused? Be sure to join the support server!"  # type: ignore

    async def send_command_help(
        self, context: Context, command: commands.Command
    ) -> None:
        embed = self.get_embed(context)
        self.common_command_formatting(context, embed, command)
        await context.respond(embed=embed)

    async def send_group_help(self, context: Context, group: commands.Group) -> None:
        subcommands = group.subcommands
        if len(subcommands) == 0:
            return await self.send_command_help(context, group)

        entries = await help_.filter_commands(context, subcommands)
        if len(entries) == 0:
            return await self.send_command_help(context, group)

        embed = self.get_embed(context)
        self.common_command_formatting(context, embed, group)

        for subcommand in subcommands:
            embed.add_field(
                name=self.get_command_signature(subcommand),
                value=self.get_command_description(subcommand),
                inline=False,
            )

        await context.respond(embed=embed)

    async def query(
        self, context: Context, iterable: typing.Iterable[commands.Command]
    ) -> typing.Optional[hikari.Embed]:
        query = self.get_arg(context)
        queries = [i.lower() for i in query.split()]

        def fmt(c: commands.Command) -> str:
            return f'{c}{"".join(c.aliases)}{self.get_command_description(c)}'

        matches = [
            y
            for z in [
                x
                for x in [
                    [
                        c.qualified_name
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
            ]
            for y in z
        ]

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
            return await self.send_plugin_help(context, matched_plugins[0])

        if len(matches) == 1:  # Just send the object if there's only 1 result
            return await context.send_help(context.bot.get_command(matches[0]))

        matches.extend([i.__class__.__name__ for i in matched_plugins])
        matches.sort(key=lambda x: (x, len(x)))
        matches = {f"`{i}`" for i in matches}
        embed = self.get_embed(context)
        embed.title = f'{plural(len(matches)):result} on "{query}"'
        embed.description = ", ".join(matches) or "Oops, seems there's nothing found"
        return embed

    def get_arg(self, context: Context) -> str:
        return context.message.content[
            len(f"{context.prefix}{context.invoked_with}") :
        ].strip()

    async def object_not_found(self, context: Context, obj: commands.Command) -> None:
        embed = await self.query(
            context,
            context.bot.commands
            if obj.__class__ is not commands.Group
            else obj.subcommands,
        )

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
