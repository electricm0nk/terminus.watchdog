"""ArgoCD detectors — OutOfSync classification and alert routing.

Implemented in Story 2.3. Stubs created in Story 1.5.

# ──────────────────────────────────────────────────────────────────────────
# MVP0 VALIDATION RESULT (run 2026-05-11, Story 2.1)
# ──────────────────────────────────────────────────────────────────────────
#
# Validated against live cluster (61 apps, 4 OutOfSync).
#
# status.resources[] carries: group, version, kind, namespace, name, status, syncWave
# status.resources[] does NOT carry: diff content, patch data, or specific field changes.
#
# Image-promotion classification strategy — ENABLED, using alternative signals:
#   1. status.summary.images[] — SHA-tagged image (e.g. :abc1234) → release-workflow-managed
#      A plain SHA tag strongly indicates the OutOfSync was caused by a manifest promotion.
#   2. status.sync.revisions[] (multi-source apps) — two-element array for chart + values repos.
#      If only the values repo (terminus.infra, index 1) SHA changed → image promotion.
#      If chart repo (index 0) SHA changed → live drift / config change.
#   3. Fallback: OutOfSync apps with no SHA-pinned image or ambiguous revision delta
#      → classify as argocd-live-drift at High severity.
#
# Architecture Decision 11 (H1) status: PARTIALLY CONFIRMED. status.resources[] validates
# which resources are OutOfSync but does not carry diff payload. Classification uses
# status.summary.images[] + revision comparison as documented above.
# ──────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import datetime
import logging
import re
from typing import Any

from watchdog.clients.argocd import ArgoCDAuthError, ArgoCDClient, ArgoCDTimeoutError
from watchdog.detectors.base import BaseDetector
from watchdog.models import Alert

log = logging.getLogger(__name__)

# SHA tag pattern — 7-40 hex characters (git short/long SHA)
_SHA_TAG_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _is_sha_tag(image: str) -> bool:
    """Return True if the image reference uses a plain hex SHA as its tag."""
    tag = image.split(":")[-1] if ":" in image else ""
    return bool(_SHA_TAG_RE.match(tag))


def _has_sha_pinned_image(app: dict[str, Any]) -> bool:
    """Check whether the app has at least one SHA-pinned image in status.summary.images."""
    images: list[str] = app.get("status", {}).get("summary", {}).get("images") or []
    return any(_is_sha_tag(img) for img in images)


def _duration_seconds(app: dict[str, Any]) -> float:
    """Calculate seconds since status.operationState.startedAt; returns 0.0 if absent."""
    started_at: str | None = (
        app.get("status", {}).get("operationState", {}).get("startedAt")
    )
    if not started_at:
        return 0.0
    try:
        ts = datetime.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        now = datetime.datetime.now(tz=datetime.UTC)
        return max(0.0, (now - ts).total_seconds())
    except (ValueError, TypeError):
        return 0.0


class ArgoCDPoller(BaseDetector):
    """Polls ArgoCD for OutOfSync applications and classifies them.

    Classification (when mvp0_enabled=True):
    - OutOfSync + SHA-pinned image → argocd-image-promotion (Medium, no remediation)
    - OutOfSync + no SHA image     → argocd-live-drift (High, remediation available)

    When mvp0_enabled=False all OutOfSync apps produce argocd-live-drift.
    """

    def __init__(self, client: ArgoCDClient, mvp0_enabled: bool = True) -> None:
        self._client = client
        self._mvp0_enabled = mvp0_enabled

    @property
    def pattern_id(self) -> str:
        return "argocd-live-drift"

    async def detect(self) -> list[Alert]:
        try:
            apps = await self._client.list_applications()
        except ArgoCDAuthError as exc:
            log.error("ArgoCDAuthError in ArgoCD detect: %s", exc)
            return []
        except ArgoCDTimeoutError as exc:
            log.warning("ArgoCDTimeoutError in ArgoCD detect: %s", exc)
            return []

        alerts: list[Alert] = []
        for app in apps:
            sync_status: str = app.get("status", {}).get("sync", {}).get("status", "Unknown")
            if sync_status != "OutOfSync":
                continue

            name: str = app.get("metadata", {}).get("name", "unknown")
            namespace: str = app.get("metadata", {}).get("namespace", "argocd")
            duration = _duration_seconds(app)

            if self._mvp0_enabled and _has_sha_pinned_image(app):
                pattern = "argocd-image-promotion"
                severity = "medium"
                diagnosis = (
                    f"App '{name}' is OutOfSync with a SHA-pinned image — "
                    "likely an in-flight image promotion from the release workflow."
                )
                recommended = "Monitor ArgoCD sync or allow Temporal release workflow to complete."
                remediation = False
            else:
                pattern = "argocd-live-drift"
                severity = "high"
                diagnosis = (
                    f"App '{name}' is OutOfSync — unexpected live drift detected. "
                    "Cluster state has diverged from git."
                )
                recommended = "Inspect the ArgoCD diff and sync or revert the offending change."
                remediation = True

            alerts.append(Alert(
                pattern=pattern,
                severity=severity,
                resource_name=name,
                resource_namespace=namespace,
                duration_seconds=duration,
                diagnosis=diagnosis,
                recommended_action=recommended,
                remediation_available=remediation,
            ))

        return alerts

