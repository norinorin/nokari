"""A module that contains custom cooldown implementation."""

import time
import typing

from lightbulb import Bucket, CooldownManager, CooldownStatus, commands, errors

from .context import Context

__all__: typing.Final[typing.List[str]] = ["cooldown"]


class CustomCooldown(CooldownManager):
    """Custom CooldownManager class with alternative hashes."""

    # pylint: disable=arguments-differ

    def __init__(
        self, *args: typing.Union[float, Bucket], **kwargs: typing.Any
    ) -> None:
        super().__init__(*args)
        self.elements: typing.Sequence[int] = kwargs.get(
            "elements", [265080794911866881]
        )
        self.alter_length: int = kwargs.get("alter_length", 0)
        self.alter_usages: int = kwargs.get("alter_usages", 1)

    def add_cooldown(self, ctx: Context) -> None:
        cooldown_hash = self.bucket.extract_hash(ctx)
        cooldown_bucket = self.cooldowns.get(cooldown_hash)
        if cooldown_bucket is not None:
            cooldown_status = cooldown_bucket.acquire()
            if cooldown_status == CooldownStatus.ACTIVE:
                raise errors.CommandIsOnCooldown(
                    "This command is on cooldown",
                    command=ctx.command,
                    retry_in=(cooldown_bucket.start_time + cooldown_bucket.length)
                    - time.perf_counter(),
                )
            if cooldown_status == CooldownStatus.INACTIVE:
                return
        if cooldown_hash in self.elements:
            self.cooldowns[cooldown_hash] = self.bucket(
                self.alter_length, self.alter_usages
            )
        else:
            self.cooldowns[cooldown_hash] = self.bucket(self.length, self.usages)
        self.cooldowns[cooldown_hash].acquire()


def cooldown(
    length: float,
    usages: int,
    bucket: Bucket,
    **kwargs: typing.Union[int, typing.Sequence[int]],
) -> typing.Callable[[commands.Command], commands.Command]:
    """Returns a decorator that applies customized cooldowns to a Command object."""

    def decorate(command: commands.Command) -> commands.Command:
        command.cooldown_manager = CustomCooldown(length, usages, bucket, **kwargs)
        return command

    return decorate
