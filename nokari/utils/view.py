"""
The MIT License (MIT)

Copyright (c) 2021 Norizon
Copyright (c) 2015-present Rapptz

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""

import typing

from lightbulb.errors import CommandSyntaxError

__all__: typing.Final[typing.List[str]] = [
    "UnexpectedQuoteError",
    "InvalidEndOfQuotedStringError",
    "ExpectedClosingQuoteError",
    "StringView",
]


class _BaseError(CommandSyntaxError):
    def __init__(self, text: typing.Optional[str] = None) -> None:
        super().__init__()
        if text is not None:
            text = text.replace("@everyone", "@\u200beveryone").replace(
                "@here", "@\u200bhere"
            )

        self.text = text


class UnexpectedQuoteError(_BaseError):
    def __init__(self, quote: str) -> None:
        self.quote = quote
        super().__init__(f"Unexpected quote mark, {quote!r}, in non-quoted string")


class InvalidEndOfQuotedStringError(_BaseError):
    def __init__(self, char: str) -> None:
        self.char = char
        super().__init__(
            f"Expected space after closing quotation but received {char!r}"
        )


class ExpectedClosingQuoteError(_BaseError):
    def __init__(self, close_quote: str) -> None:
        self.close_quote = close_quote
        super().__init__(f"Expected closing {close_quote}.")


# map from opening quotes to closing quotes
_quotes = {
    '"': '"',
    "‘": "’",
    "‚": "‛",
    "“": "”",
    "„": "‟",
    "⹂": "⹂",
    "「": "」",
    "『": "』",
    "〝": "〞",
    "﹁": "﹂",
    "﹃": "﹄",
    "＂": "＂",
    "｢": "｣",
    "«": "»",
    "‹": "›",
    "《": "》",
    "〈": "〉",
}
_all_quotes = set(_quotes.keys()) | set(_quotes.values())


class StringView:

    __slots__: typing.List[str] = ["index", "buffer", "end", "previous"]

    def __init__(self, buffer: str) -> None:
        self.index = 0
        self.buffer = buffer
        self.end = len(buffer)
        self.previous = 0

    @property
    def current(self) -> typing.Optional[str]:
        return None if self.eof else self.buffer[self.index]

    @property
    def eof(self) -> bool:
        return self.index >= self.end

    def undo(self) -> None:
        self.index = self.previous

    def skip_string(self, string: str) -> bool:
        if string == "":
            return True

        strlen = len(string)
        if self.buffer[self.index : self.index + strlen] == string.lower():
            self.previous = self.index
            self.index += strlen
            return True
        return False

    def skip_char(self, char: str) -> bool:
        ret = False
        while self.skip_string(char):
            ret = True

        return ret

    def get(self) -> typing.Optional[str]:
        try:
            return self.buffer[self.index + 1]
        except IndexError:
            return None
        finally:
            self.previous = self.index
            self.index += 1

    # pylint: disable=too-many-branches
    def get_quoted_word(self) -> typing.Optional[str]:
        current = self.current
        if current is None:
            return None

        close_quote = _quotes.get(current)

        if close_quote is not None:
            result = []
            _escaped_quotes = set(
                (
                    current,
                    close_quote,
                )
            )
        else:
            result = [current]
            _escaped_quotes = _all_quotes

        while not self.eof:
            current = self.get()
            if not current:
                if close_quote is not None:
                    # unexpected EOF
                    raise ExpectedClosingQuoteError(close_quote)
                return "".join(result)

            # currently we accept strings in the format of "hello world"
            # to embed a quote inside the string you must escape it: "a \"world\""
            if current == "\\":
                next_char = self.get()
                if not next_char:
                    # string ends with \ and no character after it
                    if close_quote is not None:
                        # if we're quoted then we're expecting a closing quote
                        raise ExpectedClosingQuoteError(close_quote)
                    # if we aren't then we just let it through
                    return "".join(result)

                if next_char in _escaped_quotes:
                    # escaped quote
                    result.append(next_char)
                else:
                    # different escape character, ignore it
                    self.undo()
                    result.append(current)
                continue

            if close_quote is None and current in _all_quotes:
                # we aren't quoted
                raise UnexpectedQuoteError(current)

            # closing quote
            if close_quote is not None and current == close_quote:
                next_char = self.get()
                if not (next_char is None or next_char.isspace()):
                    raise InvalidEndOfQuotedStringError(next_char)

                # we're quoted so it's okay
                return "".join(result)

            prev = self.index
            try:
                if (
                    current == " " or (current.isspace() and self.get() == "-")
                ) and close_quote is None:
                    # end of word found
                    return "".join(result)
            finally:
                self.index = prev

            result.append(current)

        return None

    def __repr__(self) -> str:
        return (
            f"<StringView pos: {self.index} prev: {self.previous} "
            f"end: {self.end} eof: {self.eof}>"
        )
