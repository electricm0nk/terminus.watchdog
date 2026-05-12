"""PRD Acceptance Criteria tests — Terminus Watchdog Agent."""
from __future__ import annotations

import pytest


@pytest.mark.acceptance
def test_ac_1_argocd_outsync_classification() -> None:
    """AC1 — ArgoCD OutOfSync classification end-to-end.

    Mocked OutOfSync app → argocd-live-drift High alert delivered to
    DISCORD_ALERTS_CHANNEL_ID.

    Fully implemented and pytest.skip removed in Story 2.6.
    """
    pytest.skip("Implemented in Story 2.6 — detection loop wiring")
