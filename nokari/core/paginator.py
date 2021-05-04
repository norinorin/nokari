import asyncio
import enum
from contextlib import suppress
from typing import (TYPE_CHECKING, Any, Callable, Coroutine, Dict, Final, List,
                    Optional, TypeVar, Union)

if TYPE_CHECKING:
    from nokari.core.context import Context

import hikari
from hikari import snowflakes, undefined
from lightbulb.utils import maybe_await

from nokari.utils import find, has_guild_perms

__all__: Final[List[str]] = ["EmptyPages", "Mode", "Paginator"]
_T = TypeVar("_T")
_ButtonCallback = Callable[[], Union[Any, Coroutine[Any, Any, None]]]
_Pages = List[_T]
_EventT_co = TypeVar("_EventT_co", bound=hikari.Event, covariant=True)
_PredicateT = Callable[[_EventT_co], bool]


class EmptyPages(Exception):
    pass


class Mode(enum.Enum):
    standard = 0
    remove = 1


class Paginator:
    __slots__ = (
        "allowed_mentions",
        "ctx",
        "_pages",
        "index",
        "message",
        "_task",
        "_buttons",
        "mode",
        "__weakref__",
        "loop",
        "_callback",
        "length",
        "mentions_everyone",
        "user_mentions",
        "role_mentions",
    )

    def __init__(
        self,
        ctx: "Context",
        mode: Mode = Mode.standard,
        pages: Optional[_Pages] = None,
    ):
        self.ctx: "Context" = ctx
        self.loop = ctx.bot.loop
        self._pages: _Pages = pages if pages is not None else []
        self.index: int = 0
        self.message: Optional[hikari.Message] = None
        self._task: Optional[asyncio.Task] = None
        self._buttons: Dict[str, _ButtonCallback] = {}
        self.mode: Mode = mode
        self._callback: Optional[Callable[["Paginator"], _Pages]] = None
        self.length: int = 0
        self.mentions_everyone: undefined.UndefinedOr[bool] = undefined.UNDEFINED
        self.user_mentions: undefined.UndefinedOr[
            Union[snowflakes.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = undefined.UNDEFINED
        self.role_mentions: undefined.UndefinedOr[
            Union[snowflakes.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = undefined.UNDEFINED

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, Paginator)
            and self._buttons.keys() == other._buttons.keys()
        )

    @property
    def is_paginated(self) -> bool:
        return self.length > 1

    def add_page(self, pages: Union[_T, _Pages]) -> None:
        if isinstance(pages, list):
            self._pages.extend(pages)
        else:
            self._pages.append(pages)

    def add_button(self, emoji: str, callback: _ButtonCallback) -> None:
        self._buttons[emoji] = callback

    def button(self, emoji: str) -> Callable[[_ButtonCallback], _ButtonCallback]:
        def decorator(func: _ButtonCallback) -> _ButtonCallback:
            self.add_button(emoji, func)

            return func

        return decorator

    async def stop(self, clear_reactions: bool = True) -> None:
        if not self._task:
            return

        self._task.cancel()

        if clear_reactions:
            with suppress(hikari.HTTPResponseError):
                await self.message.remove_all_reactions()  # type: ignore

        self.clean_up()

    def clean_up(self) -> None:
        with suppress(AttributeError):
            del self._pages

    async def get_page(self) -> Union[hikari.Embed, str]:
        if self._callback:
            page, length = await maybe_await(self._callback, self)
            self.length = length
        else:
            page = self._pages[self.index]
            self.length = len(self._pages)

        if not self.length:
            raise EmptyPages("The 'pages' is empty")

        return page

    async def start(self, **kwargs: Any) -> Optional[hikari.Message]:
        options = await self.kwargs

        options["paginator"] = self if self.is_paginated else None

        self.message = await self.ctx.respond(**options)

        self.ctx.bot._paginators[self.message.id] = self

        if not self.is_paginated:
            self.clean_up()
            return None

        self.loop.create_task(self.add_reactions())

        self._task = self.loop.create_task(self.run_paginator(**kwargs))

        with suppress(asyncio.CancelledError):
            if self._task is not None:
                return await self._task

        return None

    async def add_reactions(self) -> None:
        if self.message is None:
            return

        for emoji in self._buttons.keys():
            if find(
                lambda r: str(r.emoji) == emoji and r.is_me, self.message.reactions
            ):
                continue

            await self.message.add_reaction(emoji)

    async def run_paginator(
        self,
        *,
        timeout: float = 300.0,
        return_message: bool = False,
        message_timeout: float = 10.0,
        message_check: Optional[_PredicateT[hikari.MessageCreateEvent]] = None,
        reaction_check: Optional[_PredicateT[hikari.ReactionAddEvent]] = None
    ) -> Optional[hikari.Message]:
        message_check = message_check or (
            lambda x: x.author_id == self.ctx.author.id
            and x.channel_id == self.ctx.channel_id
        )

        reaction_check = reaction_check or (
            lambda x: x.user_id == self.ctx.author.id
            and x.message_id == self.message.id  # type: ignore
        )

        while True:
            try:
                events = [
                    self.ctx.bot.wait_for(
                        hikari.GuildReactionAddEvent,
                        timeout=timeout,
                        predicate=reaction_check,
                    )
                ]

                if self.mode is Mode.standard:
                    events.append(
                        self.ctx.bot.wait_for(
                            hikari.GuildReactionDeleteEvent,
                            timeout=timeout,
                            predicate=reaction_check,
                        )
                    )

                if return_message:
                    events.append(
                        self.ctx.bot.wait_for(
                            hikari.GuildMessageCreateEvent,
                            timeout=message_timeout,
                            predicate=message_check,
                        )
                    )

                done, pending = await asyncio.wait(
                    events, return_when=asyncio.FIRST_COMPLETED
                )

                try:
                    result = done.pop().result()
                except Exception:
                    raise asyncio.TimeoutError()

                for future in pending:
                    future.cancel()

                if isinstance(result, hikari.Message):
                    return result

                emoji = str(result.emoji)

                if (
                    self.mode is Mode.remove
                    and self.ctx.me is not None
                    and has_guild_perms(  # todo: check channel permissions
                        self.ctx.bot,
                        self.ctx.me,
                        hikari.Permissions.MANAGE_MESSAGES,
                    )
                    and result.member
                ):
                    await self.message.remove_reaction(result.emoji, result.member)  # type: ignore

                callback = self._buttons.get(emoji)

                if callback is None:
                    continue

                if hasattr(callback, "__self__") and callback.__self__ is self:  # type: ignore
                    await maybe_await(callback)
                else:
                    await maybe_await(callback, self)

            except asyncio.TimeoutError:
                await self.stop()

    @property
    def mentions_kwargs(self) -> Dict[str, Any]:
        return {
            "mentions_everyone": self.mentions_everyone,
            "user_mentions": self.user_mentions,
            "role_mentions": self.role_mentions,
        }

    @property
    async def kwargs(self) -> Dict[str, Any]:
        kwargs = self.mentions_kwargs
        content = await self.get_page()

        if (
            self.is_paginated
            and self.ctx.me
            and not has_guild_perms(  # todo: check channel permissions
                self.ctx.bot,
                self.ctx.me,
                hikari.Permissions.ADD_REACTIONS,
            )
        ):
            raise RuntimeError("I don't have permission to add reactions.")

        if isinstance(content, hikari.Embed):
            kwargs["embed"] = content
        else:
            kwargs["content"] = content

        return kwargs

    async def next_page(self) -> None:
        if self.index < self.length - 1:
            self.index += 1

            await self.message.edit(**(await self.kwargs))  # type: ignore

    async def previous_page(self) -> None:
        if self.index > 0:
            self.index -= 1

            await self.message.edit(**(await self.kwargs))  # type: ignore

    async def first_page(self) -> None:
        self.index = 0

        await self.message.edit(**(await self.kwargs))  # type: ignore

    async def last_page(self) -> None:
        self.index = self.length - 1

        await self.message.edit(**(await self.kwargs))  # type: ignore

    async def destroy(self) -> None:
        with suppress(hikari.HTTPResponseError):
            await self.message.delete()  # type: ignore

        if self._task is not None:
            self._task.cancel()
        self.clean_up()

    @classmethod
    def default(cls, ctx: "Context") -> "Paginator":
        self = cls(ctx)
        self.add_button("\u23ee", self.first_page)
        self.add_button("\u25c0", self.previous_page)
        self.add_button("\u25b6", self.next_page)
        self.add_button("\u23ed", self.last_page)
        self.add_button("🔴", self.stop)
        self.add_button("❌", self.destroy)
        return self
