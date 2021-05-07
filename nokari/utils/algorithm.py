"""A module that contains algorithm implementations."""
import typing

__all__: typing.Final[typing.List[str]] = ["get_luminance", "get_alt_color"]


# pylint: disable=keyword-arg-before-vararg
def get_luminance(
    rgb: typing.Optional[typing.Sequence[int]] = None, *args: int
) -> float:
    """Gets the luminance of an RGB"""

    if rgb is None:
        if not args:
            raise RuntimeError("Missing arguments...")

        rgb = args

    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def get_alt_color(
    rgb: typing.Sequence[int],
    intensity: int = 20,
    _cmp: typing.Optional[typing.Sequence[int]] = None,
) -> typing.Tuple[int, ...]:
    """Gets a darker/lighter color"""

    _cmp = _cmp or rgb
    Y = get_luminance(_cmp)
    darken = max(0.1, 1 - (intensity * 3 / 4) / 100)
    lighten = 1 + intensity / 100
    mode = Y < 128
    ret = []
    for i in rgb:
        if i < 20:
            i = 20

        i = min(255, int(i * lighten)) if mode else max(0, int(i * darken))
        ret.append(i)

    return tuple(ret)
