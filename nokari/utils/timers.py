import typing
from datetime import datetime
from weakref import WeakValueDictionary

import asyncpg
import attr
from hikari.events.base_events import Event
from hikari.internal import attr_extensions
from hikari.traits import RESTAware

TimerEventT = typing.TypeVar("TimerEventT", bound="BaseTimerEvent")


class Timer:
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

        if not (
            event := BaseTimerEvent.get_subclass(
                event_cls_name := f"{record['event']}TimerEvent"
            )
        ):
            raise RuntimeError(f"class {event_cls_name} doesn't exist.")

        self.event = event
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
    __subclasses: typing.ClassVar[
        typing.MutableMapping[str, typing.Type["BaseTimerEvent"]]
    ] = WeakValueDictionary()
    app: RESTAware = attr.field(metadata={attr_extensions.SKIP_DEEP_COPY: True})
    timer: Timer = attr.field()

    def __init_subclass__(cls: typing.Type["BaseTimerEvent"]) -> None:
        BaseTimerEvent.__subclasses[cls.__name__] = cls
        return super().__init_subclass__()

    @typing.overload
    @classmethod
    def get_subclass(cls, name: str) -> typing.Optional[typing.Type["BaseTimerEvent"]]:
        ...

    @typing.overload
    @classmethod
    def get_subclass(
        cls, name: str, default: typing.Type[TimerEventT]
    ) -> typing.Union[typing.Type["BaseTimerEvent"], typing.Type[TimerEventT]]:
        ...

    @classmethod
    def get_subclass(cls, name: typing.Any, default: typing.Any = None) -> typing.Any:
        return cls.__subclasses.get(name, default)
