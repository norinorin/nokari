from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from attr import attrib, attrs
from hikari.events.base_events import Event
from hikari.events.interaction_events import InteractionCreateEvent
from hikari.traits import RESTAware

from kita.errors import KitaError
from kita.typedefs import ICommandCallback

if TYPE_CHECKING:
    from kita.command_handlers import GatewayCommandHandler

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
    def handler(self) -> GatewayCommandHandler:
        ...


@attrs(slots=True, weakref_slot=False)
class CommandCallEvent(KitaEvent):
    app: RESTAware = attrib()
    handler: GatewayCommandHandler = attrib()
    event: InteractionCreateEvent = attrib()
    command: ICommandCallback = attrib()


@attrs(slots=True, weakref_slot=False)
class CommandFailureEvent(KitaEvent):
    app: RESTAware = attrib()
    handler: GatewayCommandHandler = attrib()
    event: InteractionCreateEvent = attrib()
    command: Optional[ICommandCallback] = attrib()
    exception: KitaError = attrib()


@attrs(slots=True, weakref_slot=False)
class CommandSuccessEvent(KitaEvent):
    app: RESTAware = attrib()
    handler: GatewayCommandHandler = attrib()
    event: InteractionCreateEvent = attrib()
    command: ICommandCallback = attrib()
