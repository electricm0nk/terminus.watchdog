"""ArgoCD order-day unsync detector — Story 2.5.

Detects etailpet-* applications that are OutOfSync during the order-day
high-priority business window (Tue 11:55 AM – Wed 11:30 PM CT).

Severity: High, bypass_quiet_hours = True (operators are always @mentioned
during the order-day window regardless of quiet-hours schedule).
"""
from __future__ import annotations

import datetime
import logging
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from watchdog.clients.argocd import ArgoCDAuthError, ArgoCDClient, ArgoCDTimeoutError
from watchdog.config import HighPriorityWindow
from watchdog.detectors.base import BaseDetector
from watchdog.models import Alert

log = logging.getLogger(__name__)

_ETAILPET_PREFIX = "etailpet-"


def is_high_priority_window_active(window: HighPriorityWindow) -> bool:
    """Return True when the current local time falls inside the high-priority window.

    Algorithm:
    1. Get now in the window's configured timezone (naive wall-clock time).
    2. Parse the rrule_str and find the most recent occurrence before now.
    3. If elapsed seconds since that occurrence <= duration_hours * 3600, return True.

    The rrule is evaluated in wall-clock (naive) time to avoid DST ambiguity in
    the occurrence-finding step.  This works because the window rule is defined
    in terms of local clock hours.
    """
    tz = ZoneInfo(window.timezone)
    now_aware = datetime.datetime.now(tz=tz)
    # Strip tzinfo: work in naive wall-clock time matching the rrule definition
    now_naive = now_aware.replace(tzinfo=None)

    # Build a naive dtstart 8 days back to ensure at least one occurrence is generated
    dtstart = now_naive - datetime.timedelta(days=8)

    # Parse inline rrule — e.g. "FREQ=WEEKLY;BYDAY=TU;BYHOUR=11;BYMINUTE=55"
    rule = rrulestr(window.rrule_str, dtstart=dtstart, ignoretz=True)

    # Find most recent occurrence at or before now
    last = rule.before(now_naive, inc=True)
    if last is None:
        return False

    elapsed_seconds = (now_naive - last).total_seconds()
    return elapsed_seconds <= window.duration_hours * 3600


class ArgoCDOrderDayDetector(BaseDetector):
    """Raises argocd-order-day-unsync for etailpet-* apps OutOfSync during order-day window.

    Alerts have bypass_quiet_hours=True so operators are always @mentioned.
    """

    def __init__(
        self,
        client: ArgoCDClient,
        window: HighPriorityWindow,
    ) -> None:
        self._client = client
        self._window = window

    @property
    def pattern_id(self) -> str:
        return "argocd-order-day-unsync"

    async def detect(self) -> list[Alert]:
        if not is_high_priority_window_active(self._window):
            return []

        try:
            apps = await self._client.list_applications()
        except ArgoCDAuthError as exc:
            log.error("ArgoCDAuthError in order-day detect: %s", exc)
            return []
        except ArgoCDTimeoutError as exc:
            log.warning("ArgoCDTimeoutError in order-day detect: %s", exc)
            return []

        alerts: list[Alert] = []
        for app in apps:
            name: str = app.get("metadata", {}).get("name", "unknown")
            if not name.startswith(_ETAILPET_PREFIX):
                continue

            sync_status: str = app.get("status", {}).get("sync", {}).get("status", "Unknown")
            if sync_status != "OutOfSync":
                continue

            namespace: str = app.get("metadata", {}).get("namespace", "argocd")

            alerts.append(Alert(
                pattern="argocd-order-day-unsync",
                severity="high",
                resource_name=name,
                resource_namespace=namespace,
                duration_seconds=0.0,
                diagnosis=(
                    f"App '{name}' is OutOfSync during the '{self._window.name}' "
                    "high-priority order-day window."
                ),
                recommended_action=(
                    "Immediately investigate the ArgoCD diff and sync or roll back "
                    "before order processing is impacted."
                ),
                remediation_available=True,
                bypass_quiet_hours=True,
            ))

        return alerts
