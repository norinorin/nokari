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
    Tuple,
    TypeVar,
    Union,
    cast,
)

import hikari
from hikari import snowflakes, undefined
from hikari.impl.special_endpoints import _ButtonBuilder
from hikari.interactions.component_interactions import ComponentInteraction

from nokari.utils import maybe_await

if TYPE_CHECKING:
    from nokari.core.context import Context

__all__: Final[List[str]] = ["EmptyPages", "Paginator"]
_T = TypeVar("_T")
_ButtonCallback = Callable[..., Union[Any, Coroutine[Any, Any, None]]]
_Callback = Callable[..., Union[Tuple[_T, int], Coroutine[Any, Any, Tuple[_T, int]]]]
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
    """A helper class for interactive menus with interactions."""

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
        "__weakref__",
    ]

    message: hikari.Message

    def __init__(
        self,
        ctx: "Context",
        pages: Optional[_Pages] = None,
        *,
        callback: Optional[_Callback] = None,
    ):
        self.ctx: "Context" = ctx

        self.index: int = 0
        self.length: int = 0

        self._pages: _Pages = pages if pages is not None else []
        self._task: Optional[asyncio.Task] = None
        self._buttons: Dict[str, ButtonWrapper] = {}
        self._callback = callback

        self.mentions_everyone: undefined.UndefinedOr[bool] = undefined.UNDEFINED
        self.user_mentions: undefined.UndefinedOr[
            Union[snowflakes.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = undefined.UNDEFINED
        self.role_mentions: undefined.UndefinedOr[
            Union[snowflakes.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = undefined.UNDEFINED

        self.component = ctx.bot.rest.build_action_row()

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

    # pylint: disable=too-many-arguments
    def add_button(
        self,
        callback: _ButtonCallback,
        /,
        *,
        style: Union[int, hikari.ButtonStyle],
        custom_id: Optional[str] = None,
        emoji: undefined.UndefinedOr[
            Union[snowflakes.Snowflakeish, hikari.Emoji]
        ] = undefined.UNDEFINED,
        label: undefined.UndefinedOr[str] = undefined.UNDEFINED,
        disable_if: Optional[_ButtonCallback] = None,
    ) -> None:
        """Adds an emoji as a button that'll invoke the callback once reacted."""
        if not emoji and not label:
            raise TypeError("Either emoji or label must be set.")

        custom_id = custom_id or callback.__name__
        self.component.add_button(style, custom_id).set_emoji(emoji).set_label(
            label
        ).add_to_container()

        # pylint: disable=unsubscriptable-object
        self._buttons[custom_id] = ButtonWrapper(
            cast(_ButtonBuilder, self.component._components[-1]), callback, disable_if
        )

    def button(
        self,
        *,
        style: Union[int, hikari.ButtonStyle],
        custom_id: Optional[str],
        emoji: undefined.UndefinedOr[
            Union[snowflakes.Snowflakeish, hikari.Emoji]
        ] = undefined.UNDEFINED,
        label: undefined.UndefinedOr[str] = undefined.UNDEFINED,
        disable_if: Optional[_ButtonCallback] = None,
    ) -> Callable[[_ButtonCallback], _ButtonCallback]:
        """Returns a decorator that will register the decorated function as the callback."""

        def decorator(func: _ButtonCallback) -> _ButtonCallback:
            self.add_button(
                func,
                style=style,
                custom_id=custom_id,
                emoji=emoji,
                label=label,
                disable_if=disable_if,
            )

            return func

        return decorator

    async def stop(self, delete_components: bool = True) -> None:
        """The default callback that stops the internal loop and does a clean up."""
        if not self._task:
            return

        self._task.cancel()

        if delete_components:
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
            page, self.length = await maybe_await(self._callback, self)
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

        if interaction := self.ctx.interaction:
            self.message = interaction.message
            await interaction.edit_initial_response(**options)
        else:
            self.message = await (await self.ctx.respond(**options)).message()

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

        paginators = self.ctx.bot.paginators

        if paginator := paginators.get(self.ctx.event.message.id):
            await paginator.stop(False)

        paginators[self.ctx.event.message.id] = self

        # Interactions' lifetime is 15 minutes.
        if timeout > 900:
            raise RuntimeError("timeout can't be greater than 15 minutes.")

        message_check = message_check or (
            lambda x: x.author_id == self.ctx.author.id
            and x.channel_id == self.ctx.channel_id
        )

        interaction_check = interaction_check or (
            lambda x: isinstance(x.interaction, ComponentInteraction)
            and x.interaction.user.id == self.ctx.author.id
            and x.interaction.message.id == self.message.id
            and x.interaction.custom_id in self._buttons
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

        await asyncio.gather(
            *[
                button_wrapper.ensure_button(self)
                for button_wrapper in self._buttons.values()
            ]
        )

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
        """The default callback that destroys the paginator."""
        with suppress(hikari.HTTPResponseError):
            await self.message.delete()

        if self._task is not None:
            self._task.cancel()

        self.clean_up()

    @classmethod
    def default(
        cls,
        ctx: "Context",
        pages: Optional[_Pages] = None,
        *,
        callback: Optional[_Callback] = None,
    ) -> "Paginator":
        """A classmethod that returns a Paginator object with the default callbacks."""
        self = cls(ctx, pages, callback=callback)
        self.add_button(
            self.first_page,
            style=hikari.ButtonStyle.PRIMARY,
            custom_id="first",
            label="First",
            # emoji="\u23ee",
            disable_if=lambda p: p.index == 0,
        )
        self.add_button(
            self.previous_page,
            style=hikari.ButtonStyle.PRIMARY,
            custom_id="back",
            label="Back",
            # emoji="\u25c0",
            disable_if=lambda p: p.index == 0,
        )
        self.add_button(
            self.next_page,
            style=hikari.ButtonStyle.PRIMARY,
            custom_id="next",
            label="Next",
            # emoji="\u25b6",
            disable_if=lambda p: p.index == p.length - 1,
        )
        self.add_button(
            self.last_page,
            style=hikari.ButtonStyle.PRIMARY,
            custom_id="last",
            label="Last",
            # emoji="\u23ed",
            disable_if=lambda p: p.index == p.length - 1,
        )

        # Gonna ditch this as we can only have 5 buttons in an action row.
        # self.add_button(hikari.ButtonStyle.DANGER, "stop", "🔴", self.stop)

        self.add_button(
            self.destroy,
            style=hikari.ButtonStyle.DANGER,
            custom_id="destroy",
            # emoji="🗑️",
            label="Delete",
        )
        return self
