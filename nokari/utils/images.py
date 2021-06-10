"""A module that contains helper function for image generating purpose."""

import typing

import numexpr
import numpy
from PIL import Image, ImageDraw, ImageFilter

U_CHAR_OVERFLOW: int = 2 << 7
PI_RAD: int = 180
__all__: typing.Final[typing.List[str]] = [
    "has_transparency",
    "round_corners",
    "get_dominant_color",
    "right_fade",
]


def has_transparency(im: Image.Image) -> bool:
    """Returns whether or not the image has transparency."""
    if im.mode == "P":
        return "transparency" in im.info

    return im.mode == "RGBA"


def round_corners(im: Image.Image, rad: int) -> None:
    """Rounds the corners of the image."""
    fill = im.getpixel((0,) * 2)
    w, h = im.size

    corner = Image.new("RGBA", (rad,) * 2, (0,) * 4)
    draw = ImageDraw.Draw(corner)
    draw.pieslice([*(0,) * 2, *(rad * 2,) * 2], PI_RAD, PI_RAD * 3 / 2, fill=fill)

    for i, coord in enumerate(
        zip([*(0,) * 2, *(w - rad,) * 2], [0, *(h - rad,) * 2, 0])
    ):
        im.paste(corner.rotate(i * 90), coord)


def get_dominant_color(im: Image.Image) -> typing.Tuple[int]:
    """Gets the color with the most occurences."""
    arr = numpy.array(im)
    a2D = arr.reshape(-1, arr.shape[-1])

    if a2D.shape[-1] == 4:
        a2D = a2D[a2D.T[-1] > 128]

    env = {
        "r": a2D[:, 0],
        "g": a2D[:, 1],
        "b": a2D[:, 2],
        "ucs": U_CHAR_OVERFLOW,
    }

    return numpy.unravel_index(
        numpy.bincount(numexpr.evaluate("r*ucs*ucs+g*ucs+b", env)).argmax(),
        (U_CHAR_OVERFLOW,) * 3,
    )


def right_fade(im: Image.Image, rad: int = 100) -> Image.Image:
    """Returns the right-faded image."""

    im = im.convert("RGBA")
    w, h = im.size

    mask = Image.new("L", (w + rad, h + rad), 255)
    m_w, m_h = mask.size
    drawmask = ImageDraw.Draw(mask)
    drawmask.rectangle(
        [m_w - rad * 3, 0, m_w, m_h],
        fill=0,
    )

    im.putalpha(
        mask.filter(ImageFilter.GaussianBlur(radius=rad)).crop(
            box=(
                rad // 2,
                rad // 2,
                m_w - rad // 2,
                m_h - rad // 2,
            )
        )
    )
    return im
