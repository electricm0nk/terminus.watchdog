"""Integration tests — require RUN_INTEGRATION_TESTS=1 to execute."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


def test_detection_loop_placeholder() -> None:
    """Placeholder — real integration test wired in Story 2.6."""
    pass
