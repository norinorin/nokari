import logging
import os
import typing

from lightbulb import Command

__all__: typing.Final[typing.List[str]] = ["require_env"]
CommandT = typing.TypeVar("CommandT", bound=Command)
_LOGGER = logging.getLogger("nokari.utils.checks")


def require_env(*vars_: str) -> typing.Callable[[Command], Command]:
    def decorator(cmd: Command) -> Command:
        if missing := [var for var in vars_ if var not in os.environ]:
            if not isinstance(cmd, Command):
                raise RuntimeError(
                    "'require_env' decorator must be above the command decorator."
                )

            _LOGGER.warning(
                "Missing %s env variable%s. %s will be disabled",
                ", ".join(missing),
                "s" * bool(missing),
                cmd.name,
            )

            cmd.disabled = True

        return cmd

    return decorator
