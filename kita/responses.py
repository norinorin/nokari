from __future__ import annotations

import sys
import typing as t

from hikari import InteractionCreateEvent
from hikari.interactions.base_interactions import MessageResponseMixin
from hikari.messages import Message

__all__ = "Response", "respond", "edit"
CREATE = sys.intern("create")
EDIT = sys.intern("edit")


def respond(
    *args: t.Any, **kwargs: t.Any
) -> t.Callable[[InteractionCreateEvent], t.Awaitable[None]]:
    return Response(CREATE, *args, **kwargs)


def edit(
    *args: t.Any, **kwargs: t.Any
) -> t.Callable[[InteractionCreateEvent], t.Awaitable[Message]]:
    return Response(EDIT, *args, **kwargs)


class Response:
    def __init__(self, type: str, *args: t.Any, **kwargs: t.Any):
        self.type = type
        self._args = args
        self._kwargs = kwargs

    @property
    def args(self) -> t.Tuple[t.Any, ...]:
        return self._args

    @property
    def kwargs(self) -> t.Dict[str, t.Any]:
        return self._kwargs

    def execute(self, event: InteractionCreateEvent) -> t.Awaitable[None]:
        interaction = event.interaction
        assert isinstance(interaction, MessageResponseMixin)
        return (
            interaction.create_initial_response
            if self.type == CREATE
            else interaction.edit_initial_response
        )(*self.args, **self.kwargs)
