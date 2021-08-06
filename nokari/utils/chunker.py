"""A module that contains chunking helper functions."""
import string
from typing import (
    Any,
    Final,
    Iterable,
    Iterator,
    List,
    Literal,
    Protocol,
    Sequence,
    TypeVar,
    overload,
)

from lightbulb import utils

from nokari.utils.view import StringView

__all__: Final[List[str]] = ["chunk", "simple_chunk", "chunk_from_list"]
T = TypeVar("T")


class Indexable(Iterable[T], Protocol[T]):
    @overload
    def __getitem__(self, key: int) -> T:
        ...

    @overload
    def __getitem__(self, key: slice) -> "Indexable[T]":
        ...

    def __iter__(self) -> Iterator[T]:
        ...


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

        if (
            not (space := utils.find(string.whitespace, lambda x: x in sliced))
            or view.eof
        ):
            if sliced:
                yield sliced
            continue

        view.undo()

        if sub := view.read(
            text.rfind(space, view.index, view.index + length + 1) - view.index
        ):
            yield sub


@overload
def simple_chunk(text: Indexable[T], length: int) -> List[Indexable[T]]:
    ...


@overload
def simple_chunk(
    text: Indexable[T], length: int, lazy: Literal[False]
) -> List[Indexable[T]]:
    ...


@overload
def simple_chunk(
    text: Indexable[T], length: int, lazy: Literal[True]
) -> Iterator[Indexable[T]]:
    ...


def simple_chunk(text: Any, length: Any, lazy: bool = False) -> Any:
    """A lite version of the chunk function."""
    return (
        ret
        if (ret := (text[n : n + length] for n in range(0, len(text), length))) and lazy
        else list(ret)
    )


def chunk_from_list(seq: Sequence[str], length: int) -> List[str]:
    ret = [""]
    index = 0

    for item in seq:
        if len(temp := f"{ret[index]}\n{item}") <= length:
            ret[index] = temp
            continue

        index += 1
        ret.append(item)

    return ret
