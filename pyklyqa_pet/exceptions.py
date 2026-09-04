"""Exceptions raised by the library."""


class KlyqaError(Exception):
    """Base class for all library errors."""


class KlyqaConnectionError(KlyqaError):
    """The device or the cloud could not be reached."""


class KlyqaAuthError(KlyqaError):
    """Authentication failed (bad credentials or token)."""


class KlyqaDeviceError(KlyqaError):
    """The device rejected the request."""

    def __init__(self, errors: list[str]) -> None:
        """Store the error messages reported by the device."""
        self.errors = errors
        super().__init__("; ".join(errors) if errors else "Device reported an error")
