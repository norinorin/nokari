from __future__ import annotations

import typing as t

from hikari import InteractionCreateEvent
from hikari.interactions.base_interactions import MessageResponseMixin

__all__ = "Response", "respond", "defer"


def respond(*args: t.Any, **kwargs: t.Any) -> Response:
    return Response(*args, **kwargs)


def defer(*args: t.Any, **kwargs: t.Any) -> Response:
    return Response(*args, **kwargs)


class Response:
    def __init__(self, *args: t.Any, **kwargs: t.Any):
        self._args = args
        self._kwargs = kwargs

    @property
    def args(self) -> t.Tuple[t.Any, ...]:
        return self._args

    @property
    def kwargs(self) -> t.Dict[str, t.Any]:
        return self._kwargs

    def _send(self, event: InteractionCreateEvent) -> t.Awaitable[None]:
        interaction = event.interaction
        assert isinstance(interaction, MessageResponseMixin)
        return interaction.create_initial_response(*self.args, **self.kwargs)
