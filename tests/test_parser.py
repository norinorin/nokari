import typing

import pytest

from nokari.plugins.api import API
from nokari.utils import ArgumentParser

tuple_io_string = [
    # input, style, hidden, card, time, color, member, remainder
    #   |      |     /      /     /     /      /     /
    ("-mtch", "2", True, True, True, None, True, ""),
    ("-mnorizon", "2", False, False, False, None, True, "norizon"),
    ("-clm", "2", False, False, False, "m", False, ""),
    ("-mcl --style=2 -s1", "1", False, True, False, None, True, "l"),
    (
        "-mc --style=dynamic remainder",
        "dynamic",
        False,
        True,
        False,
        None,
        True,
        "remainder",
    ),
    (
        '--m -h -cl="top-bottom blur"',
        "2",
        True,
        False,
        False,
        "top-bottom blur",
        False,
        "--m",
    ),
    ('"-mnorizon"', "2", False, False, False, None, False, "-mnorizon"),
    ("-mch\nline1\nline2", "2", True, True, False, None, True, "line1\nline2"),
    ("-m\n-h", "2", True, False, False, None, True, ""),
    ("-m\nh", "2", False, False, False, None, True, "h"),
    (
        "-mremainder\n-hremainder\n",
        "2",
        True,
        False,
        False,
        None,
        True,
        "remainder remainder\n",
    ),
    (
        "-mremainder\n -hremainder\n",
        "2",
        True,
        False,
        False,
        None,
        True,
        "remainder\n remainder\n",
    ),
]


@pytest.fixture
def parser() -> ArgumentParser:
    return API._spotify_argument_parser


@pytest.mark.parametrize(
    "input_string, style, hidden, card, time, color, member, remainder", tuple_io_string
)
def test_parse(
    parser: ArgumentParser,
    input_string: str,
    style: str,
    hidden: bool,
    card: bool,
    time: bool,
    color: typing.Optional[str],
    member: bool,
    remainder: str,
) -> None:
    arguments = parser.parse(input_string)
    assert arguments.style == style
    assert arguments.hidden is hidden
    assert arguments.card is card
    assert arguments.time is time
    assert arguments.color == color
    assert arguments.member is member
    assert arguments.remainder == remainder
