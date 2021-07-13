import ast
import asyncio
import importlib
import subprocess
import time
import traceback
import typing
from contextlib import redirect_stdout
from inspect import getsource
from io import StringIO

from lightbulb import Bot, checks, plugins

from nokari import core, utils
from nokari.core import Context

ZWS_ACUTE = "\u200b`"


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

    # pylint: disable=too-many-locals,exec-used,too-many-statements,lost-exception,broad-except
    @checks.owner_only()
    @core.commands.command(name="eval")
    async def _eval(self, ctx: Context, *, cmd: str) -> None:
        """Evaluates Python script."""
        env = {
            "sauce": getsource,
            "ctx": ctx,
            "bot": ctx.bot,
            "reload": importlib.reload,
            "lightbulb": __import__("lightbulb"),
            "hikari": __import__("hikari"),
            "s_dir": lambda x, y: [i for i in dir(x) if y.lower() in i],
            **globals(),
        }

        stdout = StringIO()
        result = "None"
        raw_error = ""

        # In case there are syntax errors.
        t0 = time.monotonic()
        status = False

        try:
            parsed, status, fn_name = self.clean_code(cmd)
            exec(compile(parsed, filename="<ast>", mode="exec"), env)
            with redirect_stdout(stdout):
                t0 = time.monotonic()
                result = str(await env[fn_name]()).replace("`", ZWS_ACUTE)
        except Exception:
            raw_error = (
                traceback.format_exc()
                .replace("`", ZWS_ACUTE)
                .replace(__file__, "/dev/eval.py")
            )
        finally:
            n = 1_900
            measured_time = f"⏲️ {(time.monotonic() - t0) * 1_000}ms"
            stdout_val = stdout.getvalue().replace("`", ZWS_ACUTE)

            output = f"Standard Output: ```py\n{stdout_val}```\n" if stdout_val else ""
            error = f"Standard Error: ```py\n{raw_error}```\n" if raw_error else ""
            output += error

            if not (status or error):
                output += f"Return Value: ```py\n{result}```\n"

            if not output:
                return

            if len(output) < n:
                output = f"{output}{measured_time}"
                await ctx.respond(output)
                return

            chunked_output = (
                list(utils.chunk(stdout_val.strip(), n)) if stdout_val else []
            )
            chunked_error = list(utils.chunk(raw_error.strip(), n) if raw_error else [])
            chunked_return_value = list(utils.chunk(str(result), n))

            stdout_end = len(chunked_output) - 1
            stderr_end = stdout_end + len(chunked_error) - 1

            texts = chunked_output + chunked_error

            if status:
                texts += chunked_return_value

            paginator = utils.Paginator.default(ctx)

            for idx, page in enumerate(texts):
                if chunked_output and idx <= stdout_end:
                    fmt = "Standard Output: {page}"
                elif chunked_error and idx <= stderr_end:
                    fmt = "Standard Error: {page}"
                else:
                    fmt = "Return Value: {page}"

                page = fmt.format(page=f"```py\n{page}```\n")
                page = f"{page}{measured_time} | {idx + 1}/{len(texts)}"
                paginator.add_page(page)

            # IDK if this is a good idea, w/e
            del texts
            del stdout
            del result
            del chunked_output
            del chunked_error
            del chunked_return_value
            del raw_error

            await paginator.start()

    async def run_command_in_shell(self, command: str) -> typing.List[str]:
        process = await asyncio.create_subprocess_shell(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return [output.decode() for output in await process.communicate()]

    @checks.owner_only()
    @core.command(name="bash")
    async def bash(self, ctx: Context, *, command: str) -> None:
        stdout, stderr = await self.run_command_in_shell(command)
        output = f"Stdout:\n{stdout}\n" if stdout else ""
        if stderr:
            output += f"Stderr:\n{stderr}"

        await utils.Paginator.default(
            ctx,
            pages=[
                f"```{i.replace('`', ZWS_ACUTE)}```" for i in utils.chunk(output, 1900)
            ]
            or ["No output..."],
        ).start()


def load(bot: Bot) -> None:
    bot.add_plugin(Admin(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Admin")
