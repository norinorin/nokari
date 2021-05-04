from typing import Final, Iterator, List

__all__: Final[List[str]] = ["chunks", "simple_chunks"]


def chunks(text: str, length: int) -> Iterator[str]:
    start = 0
    end = 0
    while start + length < len(text):
        sliced = text[start - 1 : start + length]
        cue = "\n" if sliced.count("\n") > 0 else " "
        end = text.rfind(cue, start, start + length + 1)
        if end - start > length or end < 0:
            start -= 1
            end = start + length

        yield text[start:end]
        start = end + 1

    yield text[start:]


def simple_chunks(text: str, length: int) -> List[str]:
    return [text[n : n + length] for n in range(0, len(text), length)]
