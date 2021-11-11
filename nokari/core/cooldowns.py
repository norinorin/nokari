"""A module that contains custom cooldown implementation."""

import typing

from lightbulb import Bucket, commands, decorators

from .context import Context

__all__: typing.Final[typing.List[str]] = ["add_cooldown"]


def add_cooldown(
    length: float,
    usages: int,
    bucket: Bucket,
    *,
    elements: typing.Optional[typing.Sequence[int]] = None,
    alter_length: float = 0,
    alter_usages: int = 1,
) -> typing.Callable[[commands.Command], commands.Command]:
    """Returns a decorator that applies customized cooldown to a Command object."""

    def callback(context: Context) -> Bucket:
        nonlocal elements
        if not elements:
            elements = [265080794911866881]

        cd_hash = bucket.extract_hash(context)
        if cd_hash in elements:
            return bucket(alter_length, alter_usages)

        return bucket(length, usages)

    return decorators.add_cooldown(callback=callback)
