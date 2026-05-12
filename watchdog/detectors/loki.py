"""Loki-based detectors for Terminus Watchdog Agent.

Detectors:
- TemporalPostgresConnectivityDetector: queries Loki for Temporal worker
  postgres connection errors; fires temporal-postgres-connectivity (High).
"""
from __future__ import annotations

import datetime
import logging

from watchdog.clients.loki import LokiClient, LokiQueryError
from watchdog.detectors.base import BaseDetector
from watchdog.models import Alert

logger = logging.getLogger(__name__)

_POSTGRES_LOGQL = '{namespace="temporal"} |= "connection refused" |= "postgres"'
_LOOK_BACK_MINUTES = 5

_DISABLED_WARNING_EMITTED: set[str] = set()


class TemporalPostgresConnectivityDetector(BaseDetector):
    """Detect Temporal worker postgres connection failures via Loki log queries.

    Fires ``temporal-postgres-connectivity`` High alert when error log lines
    matching a postgres-connection-refused pattern appear in the last
    ``_LOOK_BACK_MINUTES`` minutes.

    Disabled (returns []) when ``loki_url`` is empty.
    """

    pattern_id = "loki"

    def __init__(
        self,
        loki_client: LokiClient | None,
        loki_url: str,
    ) -> None:
        self._client = loki_client
        self._loki_url = loki_url

    async def detect(self) -> list[Alert]:
        """Return connectivity alerts if postgres errors found in Loki."""
        if not self._loki_url or self._client is None:
            if "loki-disabled" not in _DISABLED_WARNING_EMITTED:
                logger.warning(
                    "TemporalPostgresConnectivityDetector: LOKI_URL not configured — detector disabled"
                )
                _DISABLED_WARNING_EMITTED.add("loki-disabled")
            return []

        now = datetime.datetime.now(datetime.UTC)
        start = now - datetime.timedelta(minutes=_LOOK_BACK_MINUTES)

        try:
            lines = await self._client.query_range(_POSTGRES_LOGQL, start, now)
        except LokiQueryError:
            logger.error("TemporalPostgresConnectivityDetector: Loki query failed")
            return []
        except Exception:
            logger.exception("TemporalPostgresConnectivityDetector: unexpected error")
            return []

        if not lines:
            return []

        return [
            Alert(
                pattern="temporal-postgres-connectivity",
                severity="high",
                resource_name="temporal-worker",
                resource_namespace="temporal",
                duration_seconds=float(_LOOK_BACK_MINUTES * 60),
                diagnosis=(
                    f"Temporal worker postgres connection errors detected in Loki logs "
                    f"({len(lines)} error line(s) in the last {_LOOK_BACK_MINUTES} minutes)."
                ),
                recommended_action=(
                    "Check postgres pod health and network connectivity from the temporal namespace. "
                    "Run: kubectl get pods -n postgres; kubectl describe pod -n postgres <postgres-pod>"
                ),
                remediation_available=False,
            )
        ]
