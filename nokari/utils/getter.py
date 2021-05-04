"""A module that contains helper functions for searching an element in a sequence."""

from operator import attrgetter
from typing import Any, Callable, Final, Iterable, List, Optional, TypeVar

_T = TypeVar("_T")
__all__: Final[List[str]] = ["find", "get"]


def find(predicate: Callable[[_T], Any], seq: Iterable[_T]) -> Optional[_T]:
    """Copied from https://github.com/Rapptz/discord.py/blob/master/discord/utils.py"""

    for element in seq:
        if predicate(element):
            return element
    return None


def get(iterable: Iterable[_T], **attrs: Any) -> Optional[_T]:
    """Also copied from discord.py's utils.py"""
    _all = all
    attrget = attrgetter

    if len(attrs) == 1:
        _k, _v = attrs.popitem()
        pred = attrget(_k.replace("__", "."))
        for elem in iterable:
            if pred(elem) == _v:
                return elem
        return None

    converted = [
        (attrget(attr.replace("__", ".")), value) for attr, value in attrs.items()
    ]

    for elem in iterable:
        if _all(pred(elem) == value for pred, value in converted):
            return elem
    return None
