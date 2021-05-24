"""A module that contains chunking helper functions."""

from typing import Final, Iterator, List, Sequence

__all__: Final[List[str]] = ["chunk", "simple_chunk", "chunk_from_list"]


def chunk(text: str, length: int) -> Iterator[str]:
    """
    Chunks the text. This is useful for getting pages
    that'll be passed to the Paginator object.

    This will yield the chunked text split by newline character
    or by space.
    """
    start, end = 1, 0
    while (end := start + length) < len(text):
        sliced = text[start - 1 : end]
        cue = "\n" if "\n" in sliced else " "
        end = text.rfind(cue, start, end + 1)
        if end - start > length or end < 0:
            start -= 1
            end = start + length

        yield text[start:end]
        start = end + 1

    yield text[start:]


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
