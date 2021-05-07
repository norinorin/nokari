"""A module that contains chunking helper functions."""

from typing import Final, Iterator, List

__all__: Final[List[str]] = ["chunks", "simple_chunks"]


def chunks(text: str, length: int) -> Iterator[str]:
    """
    Chunks the text. This is useful for getting pages
    that'll be passed to the Paginator object.

    This will yield the chunked text split by newline character
    or by space.
    """
    start = 0
    end = 0
    while start + length < len(text):
        sliced = text[start - 1 : start + length]
        cue = "\n" if "\n" in sliced else " "
        end = text.rfind(cue, start, start + length + 1)
        if end - start > length or end < 0:
            start -= 1
            end = start + length

        yield text[start:end]
        start = end + 1

    yield text[start:]


def simple_chunks(text: str, length: int) -> List[str]:
    """A lite version of the chunks function"""
    return [text[n : n + length] for n in range(0, len(text), length)]
