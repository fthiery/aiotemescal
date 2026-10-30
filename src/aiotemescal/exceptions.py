"""Exceptions raised by aiotemescal."""


class TemescalError(Exception):
    """Base class for aiotemescal errors."""


class TemescalConnectionError(TemescalError):
    """The device cannot be reached or the connection was lost."""


class TemescalTimeoutError(TemescalConnectionError):
    """The device did not answer a request in time."""


class TemescalProtocolError(TemescalError):
    """The device sent data that cannot be decoded."""
