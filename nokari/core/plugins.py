import typing

from lightbulb.plugins import Plugin as Plugin_

__all__: typing.Final[typing.Sequence[str]] = ["Plugin"]


class Plugin(Plugin_):
    __slots__ = ("hidden",)

    def __init__(self, *args: typing.Any, hidden: bool = False, **kwargs: typing.Any):
        self.hidden = hidden
        super().__init__(*args, **kwargs)
