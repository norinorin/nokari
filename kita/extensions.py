from __future__ import annotations

import importlib
import inspect
import logging
import sys
from typing import (
    TYPE_CHECKING,
    Callable,
    Optional,
    Tuple,
    Type,
    TypeVar,
    cast,
    get_type_hints,
)

from hikari.events.base_events import Event

from kita.typedefs import (
    EventCallback,
    Extension,
    ExtensionFinalizer,
    ExtensionInitializer,
    IExtensionCallback,
)
from kita.utils import ensure_signature, is_command_parent, is_listener

if TYPE_CHECKING:
    from hikari.api.event_manager import CallbackT, EventT_co

    from kita.command_handlers import GatewayCommandHandler

__all__ = ("initializer", "finalizer", "listener")
T = TypeVar("T")
_LOGGER = logging.getLogger("kita.extensions")


def load_components(handler: GatewayCommandHandler, mod: Extension) -> None:
    for g in mod.__dict__.values():
        if is_command_parent(g):
            handler.add_command(g)
        elif is_listener(g):
            handler.subscribe(g)


def unload_components(handler: GatewayCommandHandler, mod: Extension) -> None:
    for g in mod.__dict__.values():
        if is_command_parent(g):
            handler.remove_command(g)
        elif is_listener(g):
            handler.unsubscribe(g)


def load_extension(name: str) -> Extension:
    mod = cast(Extension, importlib.import_module(name))

    if not hasattr(mod, "__einit__"):
        mod.__einit__ = None

    return mod


def unload_extension(name: str) -> Extension:
    try:
        mod = cast(Extension, sys.modules.pop(name))
    except KeyError as e:
        raise RuntimeError("extension wasn't found.") from e
    else:
        if not hasattr(mod, "__edel__"):
            mod.__edel__ = None
        return mod


def reload_extension(name: str) -> Tuple[Extension, Extension]:
    old = unload_extension(name)
    try:
        new = load_extension(name)
    except Exception as e:
        sys.modules[name] = old  # type: ignore
        raise e from None
    else:
        return old, new


def _get_module(func: IExtensionCallback) -> Optional[Extension]:
    if func.__module__ != __name__ and (mod := inspect.getmodule(func)):
        return cast(Extension, mod)

    return None


def initializer(func: IExtensionCallback) -> ExtensionInitializer:
    func = cast(ExtensionInitializer, func)
    func.__name__ = "__einit__"

    if mod := _get_module(func):
        mod.__einit__ = func

    return func


def finalizer(func: IExtensionCallback) -> ExtensionFinalizer:
    func = cast(ExtensionFinalizer, func)
    func.__name__ = "__edel__"

    if mod := _get_module(func):
        mod.__edel__ = func

    return func


def listener(
    event: Optional[Type[EventT_co]] = None,
) -> Callable[[CallbackT[EventT_co]], EventCallback[EventT_co]]:
    def decorator(func: CallbackT[EventT_co]) -> EventCallback[EventT_co]:
        cast_func = cast("EventCallback[EventT_co]", func)
        nonlocal event
        ensure_signature(cast_func)
        if event is None:
            if (
                param := next(iter(cast_func.__signature__.parameters.values()))
            ).annotation is param.empty:
                raise RuntimeError(
                    "please either provide the event type or annotate the event parameter."
                )

            annotation = param.annotation
            if not (isinstance(annotation, type) and issubclass(annotation, Event)):
                annotation = get_type_hints(func)[param.name]
            event = cast("Type[EventT_co]", annotation)

        cast_func.__etype__ = event
        cast_func.__is_listener__ = True
        return cast_func

    return decorator
