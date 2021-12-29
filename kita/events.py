from __future__ import annotations

from abc import ABC, abstractmethod

from attr import attrib, attrs
from hikari.events.base_events import Event
from hikari.traits import RESTAware

from kita.contexts import Context
from kita.errors import KitaError

__all__ = (
    "KitaEvent",
    "CommandCallEvent",
    "CommandFailureEvent",
    "CommandSuccessEvent",
)


@attrs(slots=True, weakref_slot=False)
class KitaEvent(Event, ABC):
    app: RESTAware = attrib()

    @property
    @abstractmethod
    def context(self) -> Context:
        ...


@attrs(slots=True, weakref_slot=False)
class CommandCallEvent(KitaEvent):
    app: RESTAware = attrib()
    context: Context = attrib()


@attrs(slots=True, weakref_slot=False)
class CommandFailureEvent(KitaEvent):
    app: RESTAware = attrib()
    context: Context = attrib()
    exception: KitaError = attrib()


@attrs(slots=True, weakref_slot=False)
class CommandSuccessEvent(KitaEvent):
    app: RESTAware = attrib()
    context: Context = attrib()
