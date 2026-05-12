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
