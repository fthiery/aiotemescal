"""Fixtures for the tests against a real soundbar."""

from collections.abc import AsyncGenerator
import os

import pytest

from aiotemescal import DEFAULT_PORT, TemescalClient

HOST = os.environ.get("TEMESCAL_HOST")
PORT = int(os.environ.get("TEMESCAL_PORT", DEFAULT_PORT))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip every live test when no device is configured."""
    for item in items:
        if "tests/live" in str(item.path) and not HOST:
            item.add_marker(pytest.mark.skip(reason="TEMESCAL_HOST is not set"))


@pytest.fixture
async def client() -> AsyncGenerator[TemescalClient]:
    """Return a one-shot client connected to the real device."""
    assert HOST
    async with TemescalClient(HOST, PORT) as client:
        yield client
