from abc import ABC, abstractmethod
from typing import Any, Sequence

from hikari.permissions import Permissions

from kita.typedefs import CallableProto, Extension, ICommandCallback

__all__ = (
    "KitaError",
    "MissingCommandCallbackError",
    "CommandRuntimeError",
    "CommandNameConflictError",
    "ExtensionError",
    "ExtensionInitializationError",
    "ExtensionFinalizationError",
    "CheckError",
    "CheckAnyError",
    "MissingPermissionsError",
    "MissingAnyPermissionsError",
    "GuildOnlyError",
    "DMOnlyError",
    "OwnerOnlyError",
)


class KitaError(Exception):
    ...


class MissingCommandCallbackError(KitaError):
    ...


class CommandRuntimeError(KitaError):
    def __init__(self, exception: Exception, command: ICommandCallback) -> None:
        super().__init__(
            f"callback of command {command.__name__} raised an error:\n"
            f"    {exception!r}"
        )
        self.command = command
        self.exception = exception


class CommandNameConflictError(KitaError):
    ...


class ExtensionError(KitaError):
    def __init__(self, exception: Exception, extension: Extension) -> None:
        super().__init__(
            f"extension {extension.__name__} raised an error:\n    {exception!r}"
        )
        self.exception = exception
        self.extension = extension


class ExtensionInitializationError(KitaError):
    def __init__(self, exception: Exception, extension: Extension) -> None:
        super().__init__(
            f"extension {extension.__name__} failed to initialize:\n    {exception!r}"
        )
        self.exception = exception
        self.extension = extension


class ExtensionFinalizationError(KitaError):
    def __init__(self, exception: Exception, extension: Extension) -> None:
        super().__init__(
            f"extension {extension.__name__} failed to finalize:\n    {exception!r}"
        )
        self.exception = exception
        self.extension = extension


class CheckError(KitaError):
    ...


class CheckAnyError(KitaError):
    def __init__(
        self, predicates: Sequence[CallableProto], exceptions: Sequence[BaseException]
    ) -> None:
        super().__init__("all the predicates returned False or raised errors.")
        self.predicates = predicates
        self.exceptions = exceptions


class PermissionError(KitaError, ABC):
    @property
    @abstractmethod
    def perms(self) -> Permissions:
        ...


class MissingPermissionsError(PermissionError):
    def __init__(self, perms: Permissions) -> None:
        super().__init__(f"you're missing {perms} permission(s).")
        self._perms = perms

    @property
    def perms(self) -> Permissions:
        return self._perms


class MissingAnyPermissionsError(PermissionError):
    def __init__(self, perms: Permissions) -> None:
        super().__init__(
            f"you need to have at least one of the following permissions {perms}."
        )
        self._perms = perms

    @property
    def perms(self) -> Permissions:
        return self._perms


class GuildOnlyError(KitaError):
    ...


class DMOnlyError(KitaError):
    ...


class OwnerOnlyError(KitaError):
    ...


class CommandInCooldownError(KitaError):
    def __init__(self, *args: Any, retry_after: float) -> None:
        super().__init__(*args)
        self.retry_after = retry_after
