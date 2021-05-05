"""A module that contains formatting helper functions."""

import datetime
import typing

from dateutil import relativedelta

__all__: typing.Final[typing.List[str]] = ["plural", "human_timedelta"]


class plural:
    """This will append s to the word if the value isn't 1."""

    # pylint: disable=invalid-name,too-few-public-methods

    def __init__(self, value: int, _format: bool = True) -> None:
        self.value = value
        self._format = _format

    def __format__(self, format_spec: str) -> str:
        v = self.value
        str_v = f"{v:,}" if self._format else str(v)
        singular, _, _plural = format_spec.partition("|")
        _plural = _plural or f"{singular}s"
        if abs(v) != 1:
            return f"{str_v} {_plural}"
        return f"{str_v} {singular}"


def _human_join(
    seq: typing.Sequence[str], delim: str = ", ", final: str = "and"
) -> str:
    """
    Joins all the elements and appends a word before the last element
    if the elements length > 1.
    """
    size = len(seq)
    if size == 0:
        return ""

    if size == 1:
        return seq[0]

    if size == 2:
        return f"{seq[0]} {final} {seq[1]}"

    return delim.join(seq[:-1]) + f" {final} {seq[-1]}"


def human_timedelta(
    dt_obj: datetime.datetime,
    *,
    source: typing.Optional[datetime.datetime] = None,
    accuracy: int = 3,
    brief: bool = False,
    append_suffix: bool = True,
) -> str:
    """Returns the time delta between 2 datetime objects in a human readable format."""
    now = (source or datetime.datetime.utcnow()).replace(microsecond=0)
    dt_obj = dt_obj.replace(microsecond=0)

    if dt_obj > now:
        delta = relativedelta.relativedelta(dt_obj, now)
        suffix = ""
    else:
        delta = relativedelta.relativedelta(now, dt_obj)
        suffix = " ago" if append_suffix else ""

    attrs = [
        ("year", "y"),
        ("month", "mo"),
        ("day", "d"),
        ("hour", "h"),
        ("minute", "m"),
        ("second", "s"),
    ]

    output = []
    for attr, brief_attr in attrs:
        elem = getattr(delta, attr + "s")
        if not elem:
            continue

        if attr == "day" and (weeks := delta.weeks):
            elem -= weeks * 7
            if brief:
                output.append(f"{weeks}w")
            else:
                output.append(format(plural(weeks), "week"))

        if elem <= 0:
            continue

        if brief:
            output.append(f"{elem}{brief_attr}")
            continue

        output.append(format(plural(elem), attr))

    if accuracy is not None:
        output = output[:accuracy]

    if len(output) == 0:
        return "now"

    if not brief:
        return _human_join(output) + suffix

    return " ".join(output) + suffix
