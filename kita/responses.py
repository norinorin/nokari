from __future__ import annotations

import sys
from typing import Any, Awaitable, Dict, Optional, Tuple

from hikari import InteractionCreateEvent
from hikari.interactions.base_interactions import MessageResponseMixin
from hikari.messages import Message

__all__ = "Response", "respond", "edit"
CREATE = sys.intern("create")
EDIT = sys.intern("edit")


def respond(*args: Any, **kwargs: Any) -> Response:
    return Response(CREATE, *args, **kwargs)


def edit(*args: Any, **kwargs: Any) -> Response:
    return Response(EDIT, *args, **kwargs)


class Response:
    def __init__(self, type_: str, *args: Any, **kwargs: Any):
        self.type = type_
        self._args = args
        self._kwargs = kwargs

    @property
    def args(self) -> Tuple[Any, ...]:
        return self._args

    @property
    def kwargs(self) -> Dict[str, Any]:
        return self._kwargs

    def execute(self, event: InteractionCreateEvent) -> Awaitable[Optional[Message]]:
        interaction = event.interaction
        assert isinstance(interaction, MessageResponseMixin)
        callback = (
            interaction.create_initial_response
            if self.type == CREATE
            else interaction.edit_initial_response
        )
        return callback(*self.args, **self.kwargs)  # type: ignore
