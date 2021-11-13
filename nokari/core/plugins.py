import typing

import lightbulb

from nokari.core import Nokari

__all__: typing.Final[typing.Sequence[str]] = ["Plugin"]


class Plugin(lightbulb.Plugin):
    __slots__ = ("hidden",)
    _app: Nokari
    d: lightbulb.utils.DataStore

    def __init__(self, *args: typing.Any, hidden: bool = False, **kwargs: typing.Any):
        self.hidden = hidden
        super().__init__(*args, **kwargs)

    @property
    def bot(self) -> Nokari:
        return self._app
