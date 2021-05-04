import datetime
import typing

from dateutil import relativedelta

__all__: typing.Final[typing.List[str]] = ["plural", "human_timedelta"]


class plural:
    def __init__(self, value: int, format: bool = True) -> None:
        self.value = value
        self._format = format

    def __format__(self, format_spec: str) -> str:
        v = self.value
        str_v = f"{v:,}" if self._format else str(v)
        singular, sep, plural = format_spec.partition("|")
        plural = plural or f"{singular}s"
        if abs(v) != 1:
            return f"{str_v} {plural}"
        return f"{str_v} {singular}"


def human_join(
    seq: typing.Sequence[typing.Any], delim: str = ", ", final: str = "or"
) -> str:
    size = len(seq)
    if size == 0:
        return ""

    if size == 1:
        return seq[0]

    if size == 2:
        return f"{seq[0]} {final} {seq[1]}"

    return delim.join(seq[:-1]) + f" {final} {seq[-1]}"


def human_timedelta(
    dt: datetime.datetime,
    *,
    source: typing.Optional[datetime.datetime] = None,
    accuracy: int = 3,
    brief: bool = False,
    append_suffix: bool = True,
) -> str:
    now = source or datetime.datetime.utcnow()

    now = now.replace(microsecond=0)
    dt = dt.replace(microsecond=0)

    if dt > now:
        delta = relativedelta.relativedelta(dt, now)
        suffix = ""
    else:
        delta = relativedelta.relativedelta(now, dt)
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

        if attr == "day":
            weeks = delta.weeks
            if weeks:
                elem -= weeks * 7
                if not brief:
                    output.append(format(plural(weeks), "week"))
                else:
                    output.append(f"{weeks}w")

        if elem <= 0:
            continue

        if brief:
            output.append(f"{elem}{brief_attr}")
        else:
            output.append(format(plural(elem), attr))

    if accuracy is not None:
        output = output[:accuracy]

    if len(output) == 0:
        return "now"
    else:
        if not brief:
            return human_join(output, final="and") + suffix
        else:
            return " ".join(output) + suffix
