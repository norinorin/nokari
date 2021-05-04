from operator import attrgetter
from typing import Any, Callable, Final, Iterable, List, Optional, TypeVar

T = TypeVar("T")
__all__: Final[List[str]] = ["find", "get"]


def find(predicate: Callable[[T], Any], seq: Iterable[T]) -> Optional[T]:
    """Copied from https://github.com/Rapptz/discord.py/blob/master/discord/utils.py"""

    for element in seq:
        if predicate(element):
            return element
    return None


def get(iterable: Iterable[T], **attrs: Any) -> Optional[T]:
    """Also copied from discord.py's utils.py"""
    _all = all
    attrget = attrgetter

    if len(attrs) == 1:
        k, v = attrs.popitem()
        pred = attrget(k.replace("__", "."))
        for elem in iterable:
            if pred(elem) == v:
                return elem
        return None

    converted = [
        (attrget(attr.replace("__", ".")), value) for attr, value in attrs.items()
    ]

    for elem in iterable:
        if _all(pred(elem) == value for pred, value in converted):
            return elem
    return None
