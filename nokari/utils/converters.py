import re
import typing
from datetime import datetime

import parsedatetime as pdt
import pytz
from dateutil.relativedelta import relativedelta

__all__: typing.Final[typing.List[str]] = [
    "parse_time",
]

# Mostly a copy-paste from RoboDanny.

CALENDAR = pdt.Calendar(version=pdt.VERSION_CONTEXT_STYLE)
TIME_RE = re.compile(
    """(?:(?P<years>[0-9])(?:years?|y))?
       (?:(?P<months>[0-9]{1,2})(?:months?|mo))?
       (?:(?P<weeks>[0-9]{1,4})(?:weeks?|w))?
       (?:(?P<days>[0-9]{1,5})(?:days?|d))?
       (?:(?P<hours>[0-9]{1,5})(?:hours?|h))?
       (?:(?P<minutes>[0-9]{1,5})(?:minutes?|m))?
       (?:(?P<seconds>[0-9]{1,5})(?:seconds?|s))?
    """,
    re.VERBOSE,
)


def ensure_future_time(dt: datetime, now: datetime) -> None:
    if dt < now:
        raise ValueError("The argument can't be past time.")


def parse_time(now: datetime, arg: str) -> datetime:
    if (match := TIME_RE.match(arg)) is not None and match.group(0):
        data = {k: int(v) for k, v in match.groupdict(default="0").items()}
        dt = now + relativedelta(**data)  # type: ignore
        ensure_future_time(dt, now)
        return dt

    exc = ValueError('Invalid time provided, try e.g. "next week" or "2 days".')

    if (elements := CALENDAR.nlp(arg, sourceTime=now)) is None or len(elements) == 0:
        raise exc

    n_dt, status, begin, end, _ = elements[0]

    dt = pytz.UTC.localize(n_dt)  # pylint: disable=no-value-for-parameter

    if not status.hasDateOrTime:
        raise exc

    if begin not in (0, 1) and end != len(arg):
        raise ValueError(
            "The time must be either in the beginning or end of the argument."
        )

    if not status.hasTime:
        dt = dt.replace(
            hour=now.hour,
            minute=now.minute,
            second=now.second,
            microsecond=now.microsecond,
        )

    if status.accuracy == pdt.pdtContext.ACU_HALFDAY:
        dt = dt.replace(day=now.day + 1)

    ensure_future_time(dt, now)
    return dt
