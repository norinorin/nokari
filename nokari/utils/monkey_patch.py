"""A module that monkey patches the identify payload."""

import ast
import inspect
import re
import typing

import hikari


# from https://medium.com/@chipiga86/python-monkey-patching-like-a-boss-87d7ddb8098e
def get_source(obj: typing.Any) -> str:
    """Gets the source and cleans the indentation."""
    _s = inspect.getsource(obj).split("\n")
    indent = len(_s[0]) - len(_s[0].lstrip())
    return "\n".join(i[indent:] for i in _s)


def patch(source: str, globals_: typing.Dict[str, typing.Any], obj: str) -> typing.Any:
    m = ast.parse(source)
    loc: typing.Dict[str, typing.Any] = {}
    exec(  # pylint: disable=exec-used
        compile(m, "<string>", "exec"),
        globals_,
        loc,
    )
    return loc[obj]


# enable weakref and add the hash method for MemberPresenceData
# not really aware of the side effects of it.
class MemberPresenceData(hikari.internal.cache.MemberPresenceData):
    __slots__ = ("__weakref__",)

    def __hash__(self) -> int:
        # we only cache Spotify presences
        # so guild_id doesn't matter here.
        # it seems to return the user_id instead,
        # but it might be varied, so I'll keep the hash call here
        return hash(self.user_id)


hikari.internal.cache.MemberPresenceData = MemberPresenceData  # type: ignore


def set_browser(browser: str, /) -> None:
    SOURCE = get_source(hikari.impl.shard.GatewayShardImpl._identify)
    patched = re.sub(
        r'([\'"]\$browser[\'"]:\s*f?[\'"]).+([\'"])',  # hh this regex
        fr"\1{browser}\2",
        SOURCE,
    )
    hikari.impl.shard.GatewayShardImpl._identify = patch(  # type: ignore
        patched,
        hikari.impl.shard.__dict__,
        "_identify",
    )
