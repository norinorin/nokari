import ast
import asyncio
import importlib
import subprocess
import sys
import time
import traceback
import typing
from contextlib import redirect_stdout
from inspect import getsource
from io import StringIO
from types import TracebackType

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
    def clean_code(code: str) -> typing.Tuple[typing.List[str], ast.AST, bool, str]:
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

        fn_name = "run_code"
        cmd = "\n".join(f"    {i}" for i in code.splitlines())
        raw = f"async def {fn_name}():\n{cmd}"

        parsed = ast.parse(raw)
        body = parsed.body[0].body  # type: ignore
        Admin.insert_returns(body)

        return raw.splitlines(), parsed, status, fn_name

    @staticmethod
    def format_exc(
        exc_info: typing.Tuple[
            typing.Optional[typing.Type[BaseException]],
            typing.Optional[BaseException],
            typing.Optional[TracebackType],
        ],
        raw_lines: typing.List[str],
        filename: str,
    ) -> str:
        stack = traceback.extract_tb(exc_info[-1])
        formatted = []
        for frame in stack[1:]:
            line = (
                raw_lines[frame.lineno - 1].lstrip()
                if (frame.filename == filename and not frame.line)
                else frame.line
            )
            formatted.append(
                f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n    {line}'
            )

        formatted.append(traceback.format_exception(*exc_info)[-1])

        return "Traceback (most recent call last):\n" + "\n".join(formatted)

    # pylint: disable=too-many-locals,too-many-arguments
    @staticmethod
    def get_eval_pages(
        output: str,
        error: str,
        retval: str,
        hide_retval: bool,
        measured_time: str,
        max_char: int,
    ) -> typing.Optional[typing.List[str]]:
        fmt_output = f"Standard Output: ```py\n{output}```\n" if output else ""
        fmt_output += f"Standard Error: ```py\n{error}```\n" if error else ""

        append_retval = not (hide_retval or error)

        if append_retval:
            fmt_output += f"Return Value: ```py\n{retval}```\n"

        if not fmt_output:
            return None

        if len(fmt_output) < max_char:
            return [f"{fmt_output}{measured_time}"]

        chunked_output = list(utils.chunk(output.strip(), max_char)) if output else []
        chunked_error = list(utils.chunk(error.strip(), max_char)) if error else []
        chunked_return_value = list(utils.chunk(retval, max_char))

        stdout_end = len(chunked_output) - 1
        stderr_end = stdout_end + len(chunked_error)

        print(stdout_end, stderr_end)

        texts = chunked_output + chunked_error

        if append_retval:
            texts += chunked_return_value

        pages = []

        for idx, page in enumerate(texts):
            if chunked_output and idx <= stdout_end:
                fmt = "Standard Output: {page}"
            elif chunked_error and idx <= stderr_end:
                fmt = "Standard Error: {page}"
            else:
                fmt = "Return Value: {page}"

            page = fmt.format(page=f"```py\n{page}```\n")
            page = f"{page}{measured_time} | {idx + 1}/{len(texts)}"
            pages.append(page)

        return pages

    # pylint: disable=exec-used,lost-exception,broad-except
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

        filename = "<eval>"

        stdout = StringIO()
        result = "None"
        raw_error = ""

        # In case there are syntax errors.
        t0 = time.monotonic()
        status = False
        raw_lines = None

        try:
            raw_lines, parsed, status, fn_name = self.clean_code(cmd)
            exec(compile(parsed, filename=filename, mode="exec"), env)
            with redirect_stdout(stdout):
                t0 = time.monotonic()
                result = str(await env[fn_name]()).replace("`", ZWS_ACUTE)
        except Exception:
            raw_error = (
                (
                    self.format_exc(sys.exc_info(), raw_lines, filename)
                    if raw_lines
                    else traceback.format_exc()  # Failed to compile.
                )
                .replace("`", ZWS_ACUTE)
                .replace(__file__, "/dev/eval.py")
            )
        finally:
            n = 1_900
            measured_time = f"⏲️ {(time.monotonic() - t0) * 1_000}ms"
            stdout_val = stdout.getvalue().replace("`", ZWS_ACUTE)
            pages = self.get_eval_pages(
                stdout_val, raw_error, result, status, measured_time, n
            )

            if not pages:
                return

            await utils.Paginator.default(ctx, pages=pages).start()

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
