"""A module that contains a paginator implementation."""

import asyncio
from contextlib import suppress
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    Dict,
    Final,
    List,
    Optional,
    TypeVar,
    Union,
    cast,
)

import hikari
from hikari import snowflakes, undefined
from hikari.impl.special_endpoints import ActionRowBuilder, _ButtonBuilder
from hikari.interactions.component_interactions import ComponentInteraction
from lightbulb.utils import maybe_await

if TYPE_CHECKING:
    from nokari.core.context import Context

__all__: Final[List[str]] = ["EmptyPages", "Paginator"]
_T = TypeVar("_T")
_ButtonCallback = Callable[..., Union[Any, Coroutine[Any, Any, None]]]
_Pages = List[_T]
_EventT_co = TypeVar("_EventT_co", bound=hikari.Event, covariant=True)
_PredicateT = Callable[[_EventT_co], bool]


def _handle_local_attachment(embed: hikari.Embed) -> None:
    """
    We've sent the attachments along with the components.
    So, we just need to refer to them using the `attachment://` format.
    This is just a hacky workaround for now.
    """
    if (url := str(embed.image)).startswith("attachment://"):
        embed.set_image(hikari.URL(url))

    if (url := str(embed.thumbnail)).startswith("attachment://"):
        embed.set_thumbnail(hikari.URL(url))

    if embed.footer and (url := str(embed.footer.icon)).startswith("attachment://"):
        embed.set_footer(text=embed.footer.text, icon=hikari.URL(url))

    if embed.author and (url := str(embed.author.icon)).startswith("attachment://"):
        embed.set_author(
            name=embed.author.name,
            url=embed.author.url,
            icon=hikari.URL(url),
        )


class EmptyPages(Exception):
    """
    An exception that'll get raised when the page cache is empty
    yet Paginator.start() is called.
    """


class ButtonWrapper:
    def __init__(
        self,
        button: hikari.impl.special_endpoints._ButtonBuilder,
        callback: _ButtonCallback,
        disable_if: Optional[_ButtonCallback] = None,
    ):
        self.button = button
        self.callback = callback
        self.disable_if = disable_if

    async def ensure_button(self, paginator: "Paginator") -> None:
        if self.disable_if is None:
            # Keep the state as it was
            return None

        self.button._is_disabled = bool(await maybe_await(self.disable_if, paginator))


class Paginator:
    """A helper class for interactive menus with reactions."""

    # pylint: disable=too-many-instance-attributes

    __slots__: List[str] = [
        "ctx",
        "_pages",
        "index",
        "message",
        "_task",
        "_buttons",
        "_callback",
        "length",
        "mentions_everyone",
        "user_mentions",
        "role_mentions",
        "component",
    ]

    message: hikari.Message

    def __init__(
        self,
        ctx: "Context",
        pages: Optional[_Pages] = None,
    ):
        self.ctx: "Context" = ctx

        self.index: int = 0
        self.length: int = 0

        self._pages: _Pages = pages if pages is not None else []
        self._task: Optional[asyncio.Task] = None
        self._buttons: Dict[str, ButtonWrapper] = {}
        self._callback: Optional[Callable[["Paginator"], _Pages]] = None

        self.mentions_everyone: undefined.UndefinedOr[bool] = undefined.UNDEFINED
        self.user_mentions: undefined.UndefinedOr[
            Union[snowflakes.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = undefined.UNDEFINED
        self.role_mentions: undefined.UndefinedOr[
            Union[snowflakes.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = undefined.UNDEFINED

        self.component = ActionRowBuilder()

    @property
    def is_paginated(self) -> bool:
        """Returns whether or not the message is paginated."""
        return self.length > 1

    def add_page(self, pages: Union[_T, _Pages]) -> None:
        """Appends the content or extends the pages if a list was passed."""
        if isinstance(pages, list):
            self._pages.extend(pages)
        else:
            self._pages.append(pages)

    def add_button(
        self,
        style: Union[int, hikari.ButtonStyle],
        custom_id: Optional[str],
        emoji: Union[snowflakes.Snowflakeish, hikari.Emojiish],
        callback: _ButtonCallback,
        disable_if: Optional[_ButtonCallback] = None,
    ) -> None:
        """Adds an emoji as a button that'll invoke the callback once reacted."""
        custom_id = custom_id or callback.__name__
        self.component.add_button(style, emoji=emoji, custom_id=custom_id)
        self._buttons[custom_id] = ButtonWrapper(
            cast(_ButtonBuilder, self.component._components[-1]), callback, disable_if
        )

    def button(
        self,
        style: Union[int, hikari.ButtonStyle],
        custom_id: Optional[str],
        emoji: Union[snowflakes.Snowflakeish, hikari.Emojiish],
        disable_if: Optional[_ButtonCallback] = None,
    ) -> Callable[[_ButtonCallback], _ButtonCallback]:
        """Returns a decorator that will register the decorated function as the callback."""

        def decorator(func: _ButtonCallback) -> _ButtonCallback:
            self.add_button(style, custom_id, emoji, func, disable_if)

            return func

        return decorator

    async def stop(self) -> None:
        """The default callback that stops the internal loop and does a clean up."""
        if not self._task:
            return

        self._task.cancel()

        await self.message.edit(component=None)

        self.clean_up()

    def clean_up(self) -> None:
        """Deletes the cached contents."""
        with suppress(AttributeError):
            del self._pages

    async def get_page(self) -> Union[hikari.Embed, str]:
        """
        Calls a callback if present, otherwise just get it from the cache.
        This is useful for lazy pages loading.
        """
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
        """Starts paginating the contents."""
        options = await self.kwargs
        options.pop("response_type", None)
        self.message = await self.ctx.message.respond(**options)

        if not self.is_paginated:
            self.clean_up()
            return None

        self._task = asyncio.create_task(self._run_paginator(**kwargs))

        with suppress(asyncio.CancelledError):
            return await self._task

        return None

    async def _run_paginator(
        self,
        *,
        timeout: float = 300.0,
        return_message: bool = False,
        message_timeout: float = 10.0,
        message_check: Optional[_PredicateT[hikari.MessageCreateEvent]] = None,
        interaction_check: Optional[_PredicateT[hikari.InteractionCreateEvent]] = None,
    ) -> Optional[hikari.Message]:
        """
        Runs the internal loop. This shouldn't get called.
        For general use, call Paginator.start() instead.

        This method will return a message if return_message was set to True.
        """
        message_check = message_check or (
            lambda x: x.author_id == self.ctx.author.id
            and x.channel_id == self.ctx.channel_id
        )

        interaction_check = interaction_check or (
            lambda x: isinstance(x.interaction, ComponentInteraction)
            and x.interaction.user.id == self.ctx.author.id
            and x.interaction.message_id == self.message.id
        )

        while True:
            try:
                events = [
                    self.ctx.bot.wait_for(
                        hikari.InteractionCreateEvent,
                        timeout=timeout,
                        predicate=interaction_check,
                    )
                ]

                if return_message:
                    events.append(
                        self.ctx.bot.wait_for(
                            hikari.GuildMessageCreateEvent,
                            timeout=message_timeout,
                            predicate=message_check,
                        )
                    )

                done, pending = await asyncio.wait(
                    [asyncio.create_task(event) for event in events],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                try:
                    result = done.pop().result()
                except Exception:
                    raise asyncio.TimeoutError from None

                for future in pending:
                    future.cancel()

                if isinstance(result, hikari.Message):
                    return result

                interaction = result.interaction
                callback = self._buttons[interaction.custom_id].callback

                if getattr(callback, "__self__", None) is self:
                    await maybe_await(callback, interaction)
                else:
                    await maybe_await(callback, self, interaction)

            except asyncio.TimeoutError:
                await self.stop()

    @property
    def mentions_kwargs(self) -> Dict[str, Any]:
        """
        Returns the allowed mentions to use when sending the initial message.
        By default, all the mentions are disabled.
        """
        return {
            "mentions_everyone": self.mentions_everyone,
            "user_mentions": self.user_mentions,
            "role_mentions": self.role_mentions,
        }

    @property
    async def kwargs(self) -> Dict[str, Any]:
        """
        Returns the necessary keyword arguments to use when sending and editing the message.
        """
        kwargs = self.mentions_kwargs
        content = await self.get_page()

        if isinstance(content, hikari.Embed):
            kwargs["embed"] = content

            if not content.color:
                content.color = self.ctx.color
        else:
            kwargs["content"] = content

        if self.is_paginated:
            kwargs["component"] = self.component

        for button_wrapper in self._buttons.values():
            await button_wrapper.ensure_button(self)

        kwargs["response_type"] = hikari.ResponseType.MESSAGE_UPDATE

        return kwargs

    async def edit(self, interaction: ComponentInteraction) -> None:
        kwargs = await self.kwargs

        for i in range(2):
            try:
                await interaction.create_initial_response(**kwargs)
            except ValueError:
                if not i:
                    embed = kwargs.get("embed", undefined.UNDEFINED)
                    embeds = kwargs.get("embeds", undefined.UNDEFINED)

                    if not (embed or embeds):
                        raise

                    if embed:
                        _handle_local_attachment(embed)
                    elif embeds:
                        for embed in embeds:
                            _handle_local_attachment(embed)

                    continue

                raise
            else:
                break

    async def next_page(self, interaction: ComponentInteraction) -> None:
        """The default callback that shows the next page."""
        self.index += 1
        await self.edit(interaction)

    async def previous_page(self, interaction: ComponentInteraction) -> None:
        """The default callback that shows the previous page."""
        self.index -= 1
        await self.edit(interaction)

    async def first_page(self, interaction: ComponentInteraction) -> None:
        """The default callback that shows the first page."""
        self.index = 0
        await self.edit(interaction)

    async def last_page(self, interaction: ComponentInteraction) -> None:
        """The default callback that shows the last page."""
        self.index = self.length - 1
        await self.edit(interaction)

    async def destroy(self, interaction: ComponentInteraction) -> None:
        """The default callback that shows the next page."""
        with suppress(hikari.HTTPResponseError):
            await self.message.delete()

        if self._task is not None:
            self._task.cancel()

        self.clean_up()

    @classmethod
    def default(cls, ctx: "Context") -> "Paginator":
        """A classmethod that returns a Paginator object with the default callbacks."""
        self = cls(ctx)
        self.add_button(
            hikari.ButtonStyle.PRIMARY,
            "first",
            "\u23ee",
            self.first_page,
            lambda p: p.index == 0,
        )
        self.add_button(
            hikari.ButtonStyle.PRIMARY,
            "back",
            "\u25c0",
            self.previous_page,
            lambda p: p.index == 0,
        )
        self.add_button(
            hikari.ButtonStyle.PRIMARY,
            "next",
            "\u25b6",
            self.next_page,
            lambda p: p.index == p.length - 1,
        )
        self.add_button(
            hikari.ButtonStyle.PRIMARY,
            "last",
            "\u23ed",
            self.last_page,
            lambda p: p.index == p.length - 1,
        )

        # Gonna ditch this as we can only have 5 buttons in an action row.
        # self.add_button(hikari.ButtonStyle.DANGER, "stop", "🔴", self.stop)

        self.add_button(hikari.ButtonStyle.DANGER, "destroy", "❌", self.destroy)
        return self
