from kita.typedefs import Extension, ICommandCallback

__all__ = ("KitaError", "CommandRuntimeError", "CommandNameConflictError")


class KitaError(Exception):
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


class ExtensionInilizationError(KitaError):
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
