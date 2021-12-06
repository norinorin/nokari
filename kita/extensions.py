from __future__ import annotations

import importlib
import inspect
import sys
import typing as t

from hikari.events.base_events import Event
from typing_extensions import TypeGuard

from kita.typedefs import (
    CommandCallback,
    EventCallback,
    Extension,
    ExtensionFinalizer,
    ExtensionInitializer,
    IExtensionCallback,
)
from kita.utils import ensure_signature

if t.TYPE_CHECKING:
    from hikari.api.event_manager import EventT_co

    from kita.command_handlers import GatewayCommandHandler

__all__ = ("initializer", "finalizer", "listener")
T = t.TypeVar("T")


def _is_command(obj: t.Any) -> TypeGuard[CommandCallback]:
    return (
        getattr(obj, "__is_command__", False)
        and hasattr(obj, "group")
        and hasattr(obj, "command")
    )


def _is_listener(obj: t.Any) -> TypeGuard[EventCallback]:
    return getattr(obj, "__is_listener__", False)


def _get_default_einit(_mod: Extension) -> ExtensionInitializer:
    @initializer
    def _default_einit(handler: GatewayCommandHandler) -> None:
        for g in _mod.__dict__.values():
            if _is_command(g):
                handler.add_command(g)
            elif _is_listener(g):
                handler.subscribe(g)

    return _default_einit


def _get_default_edel(_mod: Extension) -> ExtensionFinalizer:
    @finalizer
    def _default_edel(handler: GatewayCommandHandler) -> None:
        for g in _mod.__dict__.values():
            if _is_command(g):
                handler.remove_command(g)
            elif _is_listener(g):
                handler.unsubscribe(g)

    return _default_edel


def load_extension(name: str) -> Extension:
    mod = t.cast(Extension, importlib.import_module(name))

    if not hasattr(mod, "__einit__"):
        mod.__einit__ = _get_default_einit(mod)

    return mod


def unload_extension(name: str) -> Extension:
    try:
        mod = t.cast(Extension, sys.modules.pop(name))
    except KeyError as e:
        raise RuntimeError("extension wasn't found.") from e
    else:
        if not hasattr(mod, "__edel__"):
            mod.__edel__ = _get_default_edel(mod)
        return mod


def reload_extension(name: str) -> t.Tuple[Extension, Extension]:
    old = unload_extension(name)
    try:
        new = load_extension(name)
    except Exception as e:
        sys.modules[name] = old  # type: ignore
        raise e from None
    else:
        return old, new


def initializer(func: IExtensionCallback) -> ExtensionInitializer:
    func = t.cast(ExtensionInitializer, func)
    func.__name__ = "__einit__"
    return func


def finalizer(func: IExtensionCallback) -> ExtensionFinalizer:
    func = t.cast(ExtensionFinalizer, func)
    func.__name__ = "__edel__"
    return func


def listener(
    event: t.Optional[t.Type[EventT_co]] = None,
) -> t.Callable[[EventCallback[EventT_co]], EventCallback[EventT_co]]:
    def decorator(func: EventCallback[EventT_co]) -> EventCallback[EventT_co]:
        nonlocal event
        ensure_signature(func)
        if event is None:
            if (
                annotation := next(
                    iter(func.__signature__.parameters.values())
                ).annotation
            ) is inspect.Signature.empty:
                raise RuntimeError(
                    "please either provide the event type or annotate the event parameter."
                )

            assert isinstance(annotation, type) and issubclass(annotation, Event)
            event = t.cast(t.Type[EventT_co], annotation)

        func.__etype__ = event
        func.__is_listener__ = True
        return func

    return decorator
