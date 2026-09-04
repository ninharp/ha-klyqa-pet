"""Shared fixtures for the Klyqa Pet integration tests."""

from collections.abc import Generator

import pytest
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return the snapshot assertion with the Home Assistant extension."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)
