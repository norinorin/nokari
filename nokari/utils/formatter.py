"""
A module that contains formatting helper functions.
Some things were based on RoboDanny's.
"""

import datetime
import re
import typing

from dateutil import relativedelta

__all__: typing.Final[typing.List[str]] = [
    "plural",
    "human_timedelta",
    "get_timestamp",
    "discord_timestamp",
]


class plural:
    """This will append s to the word if the value isn't 1."""

    def __init__(self, value: int) -> None:
        self.value = value

    def __format__(self, format_spec: str) -> str:
        v = self.value
        fmt = ""

        # should I even use endswith here? w/e
        if format_spec[-1] == ",":
            format_spec = format_spec[:-1]
            fmt = ","

        str_v = format(v, fmt)
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
    return (
        ""
        if size == 0
        else seq[0]
        if size == 1
        else f"{seq[0]} {final} {seq[1]}"
        if size == 2
        else f"{delim.join(seq[:-1])}, {final} {seq[-1]}"
    )


# pylint: disable=too-many-branches
def human_timedelta(
    rel: typing.Union[datetime.timedelta, datetime.datetime, int, float],
    /,
    *,
    source: typing.Optional[datetime.datetime] = None,
    accuracy: int = 3,
    brief: bool = False,
    append_suffix: bool = True,
) -> str:
    """Returns the time delta in a human readable format."""
    now = (source or datetime.datetime.now(datetime.timezone.utc)).replace(
        microsecond=0
    )

    if isinstance(rel, datetime.timedelta):
        dt_obj = now + rel
    elif isinstance(rel, datetime.datetime):
        dt_obj = rel
    elif isinstance(rel, (int, float)):
        dt_obj = datetime.datetime.utcfromtimestamp(rel).replace(
            tzinfo=datetime.timezone.utc
        )
    else:
        raise TypeError(
            "rel should be either datetime, timedelta, int or float object."
        )

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
                output.append(format(plural(weeks), "week,"))

        if elem <= 0:
            continue

        if brief:
            output.append(f"{elem}{brief_attr}")
            continue

        output.append(format(plural(elem), f"{attr},"))

    if accuracy is not None:
        output = output[:accuracy]

    if len(output) == 0:
        return "now"

    if not brief:
        return _human_join(output) + suffix

    return " ".join(output) + suffix


def get_timestamp(timedelta: datetime.timedelta) -> str:
    """Gets the timestamp string of a timedelta object."""
    out = re.sub(" days?, ", ":", str(timedelta)).split(":")
    out = ":".join(f"{int(float(x)):02d}" for x in out)
    while out.startswith("00:") and len(out) > 5:
        out = out[3:]
    return re.sub(r"^0(\d:)", r"\1", out)


def escape_markdown(text: str) -> str:
    # from telegram-group-easyauth
    parse = re.sub(r"([_*\[\]()~`>\#\+\-=|\.!])", r"\\\1", text)
    return re.sub(r"\\\\([_*\[\]()~`>\#\+\-=|\.!])", r"\1", parse)


def discord_timestamp(
    obj: typing.Union[datetime.timedelta, datetime.datetime, int, float],
    /,
    *,
    fmt: str = "f",
) -> str:
    VALID_FMTS = ("t", "T", "d", "D", "f", "F", "R")
    if fmt not in VALID_FMTS:
        raise ValueError(
            f"{fmt!r} isn't valid format, please use one of {_human_join(VALID_FMTS, final='or')}"
        )

    if isinstance(obj, datetime.timedelta):
        obj = datetime.datetime.now(datetime.timezone.utc) + obj
    elif not isinstance(obj, (float, int, datetime.datetime)):
        raise TypeError(
            "obj should be either datetime.datetime, datetime.timedelta, int, or float."
        )

    if isinstance(obj, datetime.datetime):
        obj = obj.timestamp()

    return f"<t:{int(obj)}:{fmt}>"
