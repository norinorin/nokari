"""A module that contains chunking helper functions."""

import string
from typing import Final, Iterator, List, Sequence

from lightbulb import utils

from nokari.utils.view import StringView

__all__: Final[List[str]] = ["chunk", "simple_chunk", "chunk_from_list"]


def chunk(text: str, length: int) -> Iterator[str]:
    """
    Chunks the text. This is useful for getting pages
    that'll be passed to the Paginator object.

    This will yield the chunked text split by whitespaces if applicable.
    """
    view = StringView(text)

    while not view.eof:
        view.skip_ws()
        sliced = view.read(length)

        if not (sub := utils.find(string.whitespace, lambda x: x in sliced)):
            yield sliced
            continue

        view.undo()
        yield view.read(text.rfind(sub, view.index, view.index + length) - view.index)


def simple_chunk(text: str, length: int) -> List[str]:
    """A lite version of the chunks function."""
    return [text[n : n + length] for n in range(0, len(text), length)]


def chunk_from_list(seq: Sequence[str], length: int) -> List[str]:
    ret = [""]
    index = 0

    for item in seq:
        if len(temp := f"{ret[index]}\n{item}") <= length:
            ret[index] = temp
        else:
            index += 1
            ret.append(item)

    return ret
