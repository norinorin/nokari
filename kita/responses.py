from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from hikari.interactions.base_interactions import ResponseType
from hikari.messages import Message

if TYPE_CHECKING:
    from kita.contexts import Context

__all__ = "Response", "respond", "edit", "defer"
CREATE = sys.intern("create")
EDIT = sys.intern("edit")
DEFER = sys.intern("defer")


def respond(*args: Any, **kwargs: Any) -> Response:
    return Response(CREATE, *args, **kwargs)


def defer() -> Response:
    return Response(DEFER)


def edit(*args: Any, **kwargs: Any) -> Response:
    return Response(EDIT, *args, **kwargs)


def _ensure_args(args: Tuple[Any, ...]) -> Tuple[Any, ...]:
    if not (args and isinstance(args[0], ResponseType)):
        args = (ResponseType.MESSAGE_CREATE, *args)

    return args


class Response:
    __slots__ = ("type", "_args", "_kwargs")

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

    async def execute(self, ctx: Context) -> Optional[Message]:
        args = self.args
        kwargs = self.kwargs
        interaction = ctx.interaction
        res: Optional[Message] = None
        if self.type == DEFER:
            if ctx.n_message:
                # we've responded, won't be able to defer
                return None

            await interaction.create_initial_response(
                ResponseType.DEFERRED_MESSAGE_CREATE
            )
            ctx.deferring = True
            ctx.n_message += 1
            return None

        if self.type == CREATE:
            if ctx.deferring:
                # this is useful if you're not sure
                # whether or not it's deferring.
                ctx.deferring = False
                self.type = EDIT
                self.kwargs.pop("flags", None)
                self.kwargs.pop("tts", None)
                return await self.execute(ctx)

            if not ctx.n_message:  # initial
                res = await interaction.create_initial_response(
                    *_ensure_args(args), **kwargs
                )
            else:  # follow up
                res = await interaction.execute(*args, **kwargs)

            ctx.n_message += 1
        elif self.type == EDIT:
            if ctx.n_message == 1:
                res = await interaction.edit_initial_response(*args, **kwargs)
            else:
                assert ctx.last_message is not None  # can't be None
                res = await interaction.edit_message(ctx.last_message, *args, **kwargs)

        ctx.last_message = res
        return res
