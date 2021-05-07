import ast
import importlib
import re
import time
import traceback
import typing
from contextlib import redirect_stdout
from inspect import getsource
from io import StringIO

import hikari
from lightbulb import Bot, checks, plugins

from nokari import core, utils
from nokari.core import Context


class Admin(plugins.Plugin):
    """A plugin with restricted commands."""

    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot

    @staticmethod
    def insert_returns(
        body: typing.Union[typing.List[ast.AST], typing.List[ast.stmt]]
    ) -> None:
        """A static method that prepends a return statement at the last expression."""

        if not body:
            return

        if isinstance(body[-1], ast.Expr):
            body[-1] = ast.Return(body[-1].value)
            ast.fix_missing_locations(body[-1])

        if isinstance(body[-1], ast.If):
            Admin.insert_returns(body[-1].body)
            Admin.insert_returns(body[-1].orelse)

        if isinstance(body[-1], ast.With):
            Admin.insert_returns(body[-1].body)

        if isinstance(body[-1], ast.AsyncWith):
            Admin.insert_returns(body[-1].body)

    @staticmethod
    def clean_code(code: str) -> typing.Tuple[ast.AST, bool, str]:
        """Cleans the codeblock and removes the no-return flag."""
        code = code.lstrip("`")
        if code.startswith("py\n"):
            code = code[3:]

        status = False
        while (code := code.rstrip("` \n")).endswith("-nr"):
            code = code[:-3]
            status = True

        while (code := code.rstrip("` \n")).endswith("--no-return"):
            code = code[:-11]
            status = True

        fn_name = "_eval_expr"
        cmd = "\n".join(f"    {i}" for i in code.splitlines())
        body = f"async def {fn_name}():\n{cmd}"

        parsed = ast.parse(body)
        body = parsed.body[0].body  # type: ignore
        Admin.insert_returns(body)

        return parsed, status, fn_name

    # pylint: disable=too-many-locals,exec-used,too-many-statements
    @checks.owner_only()
    @core.commands.command(name="eval")
    async def _eval(self, ctx: Context, *, cmd: str) -> None:
        """Evaluates Python script"""
        env = {
            "sauce": getsource,
            "ctx": ctx,
            "bot": ctx.bot,
            "reload": importlib.reload,
            "s_dir": lambda x, y: [i for i in dir(x) if y.lower() in i],
        }
        env.update(globals())

        parsed, status, fn_name = self.clean_code(cmd)
        exec(compile(parsed, filename="<ast>", mode="exec"), env)
        func = env[fn_name]
        stdout = StringIO()
        zws = "\u200b"

        try:
            with redirect_stdout(stdout):
                t0 = time.monotonic()
                result = str(await func())
                timedelta = time.monotonic() - t0

            n = 1600
            measured_time = f"⏲️ {timedelta * 1000}ms"
            stdout_val = stdout.getvalue()

            if not status:
                output = (
                    f"Standard Output: ```py\n{stdout_val.replace('`', zws+'`')}```\n"
                    if stdout_val
                    else ""
                )
                output = (
                    f"{output}Return Value: ```py\n{result.replace('`', zws+'`')}```\n"
                )

                if len(output) < n:
                    output = f"{output}{measured_time}"
                    await ctx.respond(output)

                else:
                    chunked_output = (
                        list(utils.chunks(stdout_val.strip(), n)) if stdout_val else []
                    )
                    chunked_return_value = list(utils.chunks(str(result), n))

                    stdout_indexes = len(chunked_output) - 1

                    texts = chunked_output + chunked_return_value
                    pages = []

                    for idx, page in enumerate(texts):
                        if chunked_output and idx <= stdout_indexes:
                            page = f"Standard Output: ```py\n{page.replace('`', zws+'`')}```\n"
                        else:
                            page = f"Return Value: ```py\n{page.replace('`', zws+'`')}```\n"

                        page = f"{page}{measured_time} | {idx + 1}/{len(texts)}"
                        pages.append(page)

                    # IDK if this is a good idea, w/e
                    del texts
                    del stdout
                    del result
                    del chunked_output
                    del chunked_return_value

                    paginator = utils.Paginator.default(ctx)
                    paginator.add_page(pages)

                    await paginator.start()

        # pylint: disable=broad-except
        except Exception:
            timedelta = time.monotonic() - t0
            measured_time = f"⏲️ {timedelta * 1000}ms"
            if not status:
                try:
                    traceback_info = re.sub(
                        fr'"[\W\w]+\/{__name__}\.py"',
                        '"/dev/eval.py"',
                        traceback.format_exc(),
                    )
                    await ctx.respond(
                        f"""
Error: ```py
{traceback_info.replace('`', zws+'`')}
```
{measured_time}
"""
                    )
                except hikari.HTTPResponseError:
                    await ctx.message.add_reaction("❌")
                    self.bot.logger.error(traceback_info)


def load(bot: Bot) -> None:
    bot.add_plugin(Admin(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Admin")
