import typing
from datetime import datetime

import asyncpg
import attr
from hikari.events.base_events import Event
from hikari.internal import attr_extensions
from hikari.traits import RESTAware
from lightbulb import utils

TimerEventT = typing.TypeVar("TimerEventT", bound="BaseTimerEvent")


class Timer(typing.Generic[TimerEventT]):
    __slots__ = (
        "args",
        "kwargs",
        "event",
        "id",
        "created_at",
        "expires_at",
        "interval",
    )

    def __init__(self, record: asyncpg.Record, /):
        self.id: int = record["id"]

        extra = record["extra"]
        self.args: typing.Tuple[typing.Any, ...] = extra.get("args", [])
        self.kwargs: typing.Dict[str, typing.Any] = extra.get("kwargs", {})

        # O(n) but who cares
        event_cls_name = f"{record['event']}TimerEvent"
        if (
            event := utils.find(
                BaseTimerEvent.__subclasses__(),
                lambda cls: cls.__name__ == event_cls_name,
            )
        ) is None:
            raise RuntimeError(f"class {event_cls_name} doesn't exist.")

        self.event: TimerEventT = event
        self.created_at: datetime = record["created_at"]
        self.expires_at: datetime = record["expires_at"]
        self.interval: typing.Optional[int] = record["interval"]

    @classmethod
    def temporary(
        cls,
        *,
        expires_at: datetime,
        created_at: datetime,
        event: str,
        interval: typing.Optional[int] = None,
        args: typing.Any,
        kwargs: typing.Any,
    ) -> "Timer":
        return cls(
            {
                "id": None,
                "extra": {"args": args, "kwargs": kwargs},
                "event": event,
                "created_at": created_at,
                "expires_at": expires_at,
                "interval": interval,
            }
        )

    def __eq__(self, other: typing.Any) -> bool:
        return self.id == getattr(other, "id", None)

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return (
            f"<Timer created_at={self.created_at} "
            f"expires_at={self.expires_at} "
            f"event={self.event} "
            f"interval={self.interval} "
            f"extra={{args={self.args}, "
            f"kwargs={self.kwargs}}}>"
        )


@attr_extensions.with_copy
@attr.define(kw_only=True, weakref_slot=False)
class BaseTimerEvent(Event):
    app: RESTAware = attr.field(metadata={attr_extensions.SKIP_DEEP_COPY: True})

    timer: Timer = attr.field()
