"""A module that monkey patches the identify payload"""

import ast
import inspect
import re
import typing

import hikari


# from https://medium.com/@chipiga86/python-monkey-patching-like-a-boss-87d7ddb8098e
def source(obj: typing.Any) -> str:
    """Gets the source and cleans the indentation."""
    _s = inspect.getsource(obj).split("\n")
    indent = len(_s[0]) - len(_s[0].lstrip())
    return "\n".join(i[indent:] for i in _s)


SOURCE = source(hikari.impl.shard.GatewayShardImpl._identify)

patched = re.sub(
    r'([\'"]\$browser[\'"]:\s*f?[\'"]).+([\'"])',  # hh this regex
    r"\1Discord Android\2",
    SOURCE,
)

m = ast.parse(patched)

loc: typing.Dict[str, typing.Any] = {}

exec(  # pylint: disable=exec-used
    compile(m, "<string>", "exec"),
    hikari.impl.shard.__dict__,
    loc,
)

hikari.impl.shard.GatewayShardImpl._identify = loc["_identify"]  # type: ignore
