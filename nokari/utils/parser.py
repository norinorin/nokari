from __future__ import annotations

import sys
import time
import typing
from functools import partial
from types import SimpleNamespace

from lightbulb import utils

from .view import StringView, UnexpectedQuoteError

if typing.TYPE_CHECKING:
    from nokari.core import Context

TRUE = sys.intern("TRUE")


class Cursor:
    def __init__(self, parser: ArgumentParser, argument: str) -> None:
        self.view = StringView(argument)
        self.parser = parser
        self.current = parser._remainder
        self.data: typing.Dict[str, typing.List[str]] = {self.current: []}

    @property
    def remainder(self) -> str:
        return self.parser._remainder

    @property
    def short_flags(self) -> typing.Dict[str, str]:
        return self.parser.short_flags

    @property
    def short_options(self) -> typing.Dict[str, str]:
        return self.parser.short_options

    @property
    def long_flags(self) -> typing.Dict[str, str]:
        return self.parser.long_flags

    @property
    def long_options(self) -> typing.Dict[str, str]:
        return self.parser.long_options

    def iterator(self) -> typing.Iterator[typing.Tuple[str, bool]]:
        while not self.view.eof:
            # we only wanna skip space, not other whitespaces
            self.view.skip_char(" ")
            index = self.view.index
            valid = self.view.buffer[index:].lstrip().startswith("-")

            # no"rizon" by default is invalid
            # we're gonna make it valid here
            # it'll be parsed as norizon
            try:
                argument = self.view.get_quoted_word() or ""
            except UnexpectedQuoteError:
                argument = self.view.buffer[index : self.view.index] + (
                    self.view.get_quoted_word() or ""
                )

            yield argument, valid

    def append(self, argument: str) -> None:
        if not (argument := argument.lstrip()):
            return

        argmax = (
            -1
            if self.remainder == self.current
            else self.parser.args[self.current]["argmax"]
        )

        if self.current not in self.data or len(self.data[self.current]) == argmax:
            self.data[self.current] = []

        self.data[self.current].append(argument)

        if len(self.data[self.current]) == argmax:
            self.current = self.remainder

    def parse_argument(self, argument: str) -> typing.Optional[str]:
        argument = argument.lstrip()
        length = len(argument)

        if length >= 4 and "=" in argument:
            return self.parse_key_with_equals_sign(argument)

        if length >= 2 and argument[0] == "-" and argument[1] not in ("-", " "):
            return self.parse_short_keys(argument)

        if (
            length >= 3
            and argument.startswith("--")
            and argument[2] not in ("-", " ")
            and self.parse_key(argument)
        ):
            return None

        return argument

    def parse_short_keys(self, argument: str) -> str:
        key = argument[1:]
        short_options: typing.Set[str] = {
            option.lstrip("-") for option in self.short_options
        }
        option = utils.find(short_options, key.startswith)

        if option:
            self.current = self.short_options[f"-{option}"]
            return key[len(option) :]

        short_flags: typing.Set[str] = {flag.lstrip("-") for flag in self.short_flags}
        used_flags: typing.Set[str] = set()

        while key:
            flag = utils.find(
                short_flags, lambda x: x not in used_flags and key.startswith(x)
            )

            if not flag:
                break

            used_flags.add(flag)
            key = key[len(flag) :]
            self.data[self.short_flags[f"-{flag}"]] = [TRUE]
        else:
            return key

        self.current = self.remainder
        return key

    def parse_key(self, argument: str) -> bool:
        if flag := {**self.short_flags, **self.long_flags}.get(argument):
            self.data[flag] = [TRUE]
            return True

        self.current = {**self.short_options, **self.long_options}.get(
            argument, self.remainder
        )

        return not (self.current == self.remainder and self.parser.consume_keys)

    def parse_key_with_equals_sign(self, argument: str) -> str:
        key, _, arg = argument.partition("=")
        if not key or not key.startswith("-") or not arg:
            self.current = self.remainder
            return argument

        if not self.parse_key(key):
            return argument

        return arg

    def get_parsed_data(
        self,
    ) -> typing.Dict[str, typing.Union[typing.Literal[None], bool, str, float]]:
        data = typing.cast(
            typing.Dict[str, typing.Union[typing.Literal[None], bool, str, float]],
            self.data,
        )
        data[self.remainder] = " ".join(
            typing.cast(typing.List[str], data[self.remainder])
        )

        for k, v in self.parser.args.items():
            arg = data.pop(k, None)
            argmax = v["argmax"]

            if arg is None:
                data[k] = (
                    False
                    if (default := v["default"]) is None and argmax == 0
                    else default
                )
                continue

            # special key
            if k == "time":
                data[k] = time.time()
                continue

            val = " ".join(typing.cast(typing.List[str], arg))
            data[k] = val is TRUE if argmax == 0 else val

        return data

    def fetch_arguments(self) -> SimpleNamespace:
        for argument, valid in self.iterator():

            if not valid:
                self.append(argument)
                continue

            remainder = self.parse_argument(argument)

            if remainder:
                self.append(remainder)

        return SimpleNamespace(**self.get_parsed_data())


class ArgumentInfo(typing.TypedDict):
    argmax: int
    default: typing.Any


class PartialArgument(typing.Protocol):
    def __call__(
        self, *keys: str, argmax: int = -1, default: typing.Any = None
    ) -> ArgumentParser:
        ...


class ArgumentParser:
    def __init__(self, append_invalid_keys_to_remainder: bool = True) -> None:
        self.args: typing.Dict[str, ArgumentInfo] = {}
        self._remainder = "remainder"
        self.short_flags: typing.Dict[str, str] = {}
        self.short_options: typing.Dict[str, str] = {}
        self.long_flags: typing.Dict[str, str] = {}
        self.long_options: typing.Dict[str, str] = {}
        self.consume_keys = append_invalid_keys_to_remainder

    def argument(
        self,
        name: str,
        /,
        *keys: str,
        argmax: int = -1,
        default: typing.Any = None,
    ) -> ArgumentParser:
        if not keys:
            return self.remainder(name)

        long_keys = {k for k in keys if k.startswith("--")}
        short_keys = {k for k in keys if k not in long_keys and k.startswith("-")}

        if not long_keys and not short_keys:
            raise RuntimeError("Expected keys in --key or -k format")

        for key in short_keys:
            if argmax == 0:
                self.short_flags[key] = name
                continue

            self.short_options[key] = name

        for key in long_keys:
            if argmax == 0:
                self.long_flags[key] = name
                continue

            self.long_options[key] = name

        self.args[name] = ArgumentInfo(argmax=argmax, default=default)

        return self

    def remainder(self, name: str, /) -> ArgumentParser:
        self._remainder = name
        return self

    def parse(self, ctx: typing.Optional[Context], argument: str) -> SimpleNamespace:
        if ctx and ctx.parsed_arg:
            return ctx.parsed_arg

        ret = Cursor(self, argument).fetch_arguments()

        if ctx:
            ctx.parsed_arg = ret

        return ret

    def __getattr__(self, attr: str) -> PartialArgument:
        return partial(self.argument, attr)
