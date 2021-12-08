"""A module that contains chunking helper functions."""
import string
from typing import (
    Any,
    Final,
    Iterable,
    Iterator,
    List,
    Literal,
    Optional,
    Protocol,
    Sequence,
    TypeVar,
    overload,
)

from kita import find

__all__: Final[List[str]] = ["chunk", "simple_chunk", "chunk_from_list"]
T = TypeVar("T")


class Indexable(Iterable[T], Protocol[T]):
    @overload
    def __getitem__(self, key: int) -> T:
        ...

    @overload
    def __getitem__(self, key: slice) -> "Indexable[T]":
        ...

    # pylint: disable=non-iterator-returned
    def __iter__(self) -> Iterator[T]:
        ...


class _StringView:
    __slots__ = ("_idx", "buffer", "n", "prev")

    def __init__(self, buffer: str):
        self._idx = 0
        self.buffer = buffer
        self.n = len(buffer)
        self.prev = 0

    @property
    def is_eof(self) -> bool:
        return self.idx >= self.n

    @property
    def idx(self) -> int:
        return self._idx

    @idx.setter
    def idx(self, val: int) -> None:
        self.prev = self._idx
        self._idx = val

    def undo(self) -> None:
        self.idx = self.prev
        return None

    def skip_ws(self) -> None:
        prev = self.idx
        if (char := self.get_current()) is not None and not char.isspace():
            return None
        while (char := self.get_char()) is not None and char.isspace():
            pass
        self.prev = prev

    def get_char(self) -> Optional[str]:
        self.idx += 1
        return self.get_current()

    def get_current(self) -> Optional[str]:
        return None if self.is_eof else self.buffer[self.idx]

    def read(self, n: int) -> str:
        self.idx += n
        return self.buffer[self.prev : self.idx]


def chunk(text: str, length: int) -> Iterator[str]:
    """
    Chunks the text. This is useful for getting pages
    that'll be passed to the Paginator object.

    This will yield the chunked text split by whitespaces if applicable.
    """
    view = _StringView(text)

    while not view.is_eof:
        view.skip_ws()
        sliced = view.read(length)

        if not (space := find(lambda x: x in sliced, string.whitespace)) or view.is_eof:
            if sliced:
                yield sliced
            continue

        view.undo()

        if sub := view.read(
            text.rfind(space, view.idx, view.idx + length + 1) - view.idx
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


# pylint: disable=used-before-assignment
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
