"""
Example:

# -1 is Greedy
#  0 is Flag
#  else Option

parser = (
    ArgumentParser()
    .argument("test", "--test", "-t", argmax=0, default=False)
    .argument("member", "--member", "-m", argmax=-1, default="")
)
"""
# ^ actually that was just a plan
# so that I had the big picture of what I wanted to achieve

from __future__ import annotations

import sys
import typing
from types import SimpleNamespace

from lightbulb import utils

from .view import StringView, UnexpectedQuoteError, _quotes

INVALID_OPENINGS = tuple(f"{quote}-" for quote in _quotes)
TRUE = sys.intern("TRUE")
FALSE = sys.intern("FALSE")


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
    def long_keys(self) -> typing.Dict[str, str]:
        return self.parser.long_keys

    def iterator(self) -> typing.Iterator[typing.Tuple[str, bool]]:
        while not self.view.eof:
            # we only wanna skip space, not other whitespaces
            self.view.skip_char(" ")

            # we wanna treat it as argument if it starts with "-
            valid = not self.view.buffer.startswith(INVALID_OPENINGS)

            # no"rizon" by default is invalid
            # we're gonna make it valid here
            # it'll be parsed as norizon
            try:
                index = self.view.index
                argument = self.view.get_quoted_word() or ""
            except UnexpectedQuoteError:
                argument = self.view.buffer[index : self.view.index] + (
                    self.view.get_quoted_word() or ""
                )

            yield argument, valid

    def append(self, argument: str) -> None:
        argmax = (
            -1
            if self.remainder == self.current
            else self.parser.args[self.current]["argmax"]
        )

        if self.current not in self.data or len(self.data[self.current]) == argmax:
            self.data[self.current] = []

        self.data[self.current].append(argument)

    def parse_argument(self, argument: str) -> typing.Optional[str]:
        length = len(argument)
        if length >= 4 and "=" in argument:
            return self.parse_key_with_equals_sign(argument)

        if length >= 2 and argument[0] == "-" and argument[1] not in ("-", " "):
            return self.parse_short_keys(argument)

        if length >= 3 and argument.startswith("--") and argument[2] not in ("-", " "):
            self.parse_key(argument)
            return None

        return argument

    def parse_short_keys(self, argument: str) -> str:
        key = argument[1:]
        short_flags: typing.Set[str] = {flag.lstrip("-") for flag in self.short_flags}
        short_options: typing.Set[str] = {
            option.lstrip("-") for option in self.short_options
        }
        used_flags: typing.Set[str] = set()

        option = utils.find(short_options, key.startswith)

        if option:
            self.current = self.short_options[f"-{option}"]
            return key[len(option) :]

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

    def parse_key(self, argument: str) -> None:
        self.current = {**self.short_flags, **self.long_keys, **self.short_options}.get(
            argument, self.remainder
        )

    def parse_key_with_equals_sign(self, argument: str) -> str:
        key, _, arg = argument.partition("=")
        if not key or not arg:
            self.current = self.remainder
            return argument

        self.parse_key(key)
        return arg

    def get_parsed_data(
        self,
    ) -> typing.Dict[str, typing.Union[typing.Literal[None], bool, str]]:
        data = typing.cast(
            typing.Dict[str, typing.Union[typing.Literal[None], bool, str]],
            self.data.copy(),
        )
        data[self.remainder] = " ".join(
            typing.cast(typing.List[str], data[self.remainder])
        ).strip()

        for k, v in self.parser.args.items():
            arg = data.get(k)
            argmax = v["argmax"]

            if arg is None:
                data[k] = (
                    False
                    if (default := v["default"]) is None and argmax == 0
                    else default
                )
                continue

            val = " ".join(self.data[k])
            data[k] = val is TRUE if argmax == 0 else val

        return data

    def fetch_arguments(self) -> SimpleNamespace:
        for argument, valid in self.iterator():
            if not valid:
                self.append(argument)
                continue

            remainder = self.parse_argument(argument)

            if remainder is not None:
                self.append(remainder)

        return SimpleNamespace(**self.get_parsed_data())


class ArgumentInfo(typing.TypedDict):
    long: typing.Optional[str]
    short: typing.Optional[str]
    argmax: int
    default: typing.Any


class ArgumentParser:
    def __init__(self) -> None:
        self.args: typing.Dict[str, ArgumentInfo] = {}
        self._remainder = "remainder"
        self.short_flags: typing.Dict[str, str] = {}
        self.short_options: typing.Dict[str, str] = {}
        self.long_keys: typing.Dict[str, str] = {}

    def argument(
        self,
        name: str,
        long: typing.Union[str, typing.List[str], typing.Literal[None]],
        short: typing.Optional[str],
        /,
        *,
        argmax: int = -1,
        default: typing.Any = None,
    ) -> ArgumentParser:
        if argmax == 0 and short:
            self.short_flags[short] = name
        elif short:
            self.short_options[short] = name

        if isinstance(long, str):
            long = [long]

        if isinstance(long, list):
            for key in long:
                self.long_keys[key] = name

            long = long.pop(0)

        self.args[name] = ArgumentInfo(
            long=long, short=short, argmax=argmax, default=default
        )

        return self

    def remainder(self, name: str, /) -> ArgumentParser:
        self._remainder = name
        return self

    def parse(self, argument: str) -> SimpleNamespace:
        cur = Cursor(self, argument)
        return cur.fetch_arguments()
