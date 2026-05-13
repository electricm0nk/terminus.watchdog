"""Temporal workflow anomaly detectors.

Detectors:
- TemporalZombieDetector: zombie-activity (>2h, Medium) and zombie-critical (>24h, High)
- TemporalStaleDetector: stale-workflow (no history events >30min, Medium)
"""
from __future__ import annotations

import datetime
import logging

from watchdog.clients.temporal import TemporalClient
from watchdog.detectors.base import BaseDetector
from watchdog.models import Alert

logger = logging.getLogger(__name__)

# Default thresholds (overridden by Settings in Story 3.6)
_ZOMBIE_ACTIVITY_HOURS = 2
_ZOMBIE_CRITICAL_HOURS = 24
_STALE_WORKFLOW_MINUTES = 30


class TemporalZombieDetector(BaseDetector):
    """Detect workflows that have been running longer than expected.

    Emits:
    - ``temporal-zombie-critical`` (High) when elapsed > ZOMBIE_CRITICAL_HOURS (default 24h)
    - ``temporal-zombie-activity`` (Medium) when elapsed > ZOMBIE_ACTIVITY_HOURS (default 2h)

    For a single workflow only the highest-severity pattern is emitted.
    """

    pattern_id = "temporal-zombie"

    def __init__(
        self,
        temporal_client: TemporalClient,
        zombie_activity_hours: int = _ZOMBIE_ACTIVITY_HOURS,
        zombie_critical_hours: int = _ZOMBIE_CRITICAL_HOURS,
    ) -> None:
        self._client = temporal_client
        self._zombie_activity_hours = zombie_activity_hours
        self._zombie_critical_hours = zombie_critical_hours

    async def detect(self) -> list[Alert]:
        """Return zombie alerts for any running workflows beyond the thresholds."""
        now = datetime.datetime.now(datetime.UTC)
        alerts: list[Alert] = []

        try:
            workflows = await self._client.list_running_workflows()
        except Exception:
            logger.exception("TemporalZombieDetector: failed to list running workflows")
            return []

        for wf in workflows:
            elapsed = now - wf.start_time
            elapsed_hours = elapsed.total_seconds() / 3600

            if elapsed_hours > self._zombie_critical_hours:
                pattern = "temporal-zombie-critical"
                severity = "high"
                threshold_desc = f"{self._zombie_critical_hours}h"
                # >24h zombie: auto-terminate is safe — clearly stuck
                remediation_available = True
            elif elapsed_hours > self._zombie_activity_hours:
                pattern = "temporal-zombie-activity"
                severity = "medium"
                threshold_desc = f"{self._zombie_activity_hours}h"
                # 2-24h zombie: alert only — may still be legitimately running
                remediation_available = False
            else:
                continue

            elapsed_display = _format_elapsed(elapsed)
            alerts.append(
                Alert(
                    pattern=pattern,
                    severity=severity,
                    resource_name=wf.id,
                    resource_namespace=wf.task_queue,
                    duration_seconds=elapsed.total_seconds(),
                    diagnosis=(
                        f"Temporal workflow '{wf.id}' has been running for {elapsed_display}, "
                        f"exceeding the {threshold_desc} threshold. "
                        "May indicate a stuck or hung execution."
                    ),
                    recommended_action=(
                        "Inspect the workflow in the Temporal Web UI. "
                        "Terminate if confirmed stuck or no longer needed."
                    ),
                    remediation_available=remediation_available,
                )
            )

        return alerts


class TemporalStaleDetector(BaseDetector):
    """Detect running workflows with no new history events for > STALE_WORKFLOW_MINUTES.

    Tracks ``history_length`` per ``run_id`` across poll cycles.
    On the first poll, a workflow is added to tracking without firing an alert (baseline).
    Emits ``temporal-stale-workflow`` Medium alert when history_length is unchanged
    for more than the threshold duration.
    """

    pattern_id = "temporal-stale"

    def __init__(
        self,
        temporal_client: TemporalClient,
        stale_minutes: int = _STALE_WORKFLOW_MINUTES,
    ) -> None:
        self._client = temporal_client
        self._stale_minutes = stale_minutes
        # {run_id: (history_length, last_changed_at)}
        self._history_tracking: dict[str, tuple[int, datetime.datetime]] = {}

    async def detect(self) -> list[Alert]:
        """Return stale alerts for workflows with no history progress beyond the threshold."""
        now = datetime.datetime.now(datetime.UTC)
        alerts: list[Alert] = []

        try:
            workflows = await self._client.list_running_workflows()
        except Exception:
            logger.exception("TemporalStaleDetector: failed to list running workflows")
            return []

        # Track which run_ids are still alive for cleanup
        active_run_ids: set[str] = set()

        for wf in workflows:
            run_id = wf.run_id
            current_length: int = wf.history_length
            active_run_ids.add(run_id)

            if run_id not in self._history_tracking:
                # First time we see this workflow — establish baseline, no alert
                self._history_tracking[run_id] = (current_length, now)
                continue

            tracked_length, last_changed = self._history_tracking[run_id]

            if current_length != tracked_length:
                # History is progressing — update baseline
                self._history_tracking[run_id] = (current_length, now)
                continue

            # History unchanged — check elapsed time since last change
            elapsed = now - last_changed
            if elapsed.total_seconds() >= self._stale_minutes * 60:
                elapsed_display = _format_elapsed(elapsed)
                alerts.append(
                    Alert(
                        pattern="temporal-stale-workflow",
                        severity="medium",
                        resource_name=wf.id,
                        resource_namespace=wf.task_queue,
                        duration_seconds=elapsed.total_seconds(),
                        diagnosis=(
                            f"Temporal workflow '{wf.id}' has had no new history events "
                            f"for {elapsed_display}. It may be stuck waiting on a signal "
                            "or timer with no visible progress."
                        ),
                        recommended_action=(
                            "Check workflow state in Temporal Web UI. "
                            "If stuck on a timer or signal, inspect workflow code for blocking operations."
                        ),
                        remediation_available=False,
                    )
                )

        # Clean up tracking for workflows no longer running
        stale_ids = set(self._history_tracking.keys()) - active_run_ids
        for run_id in stale_ids:
            del self._history_tracking[run_id]

        return alerts


def _format_elapsed(delta: datetime.timedelta) -> str:
    """Format a timedelta as a human-readable string (e.g. '3h 15m')."""
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _extract_service_name(workflow_id: str) -> str:
    """Extract service name from a ReleaseWorkflow ID.

    Format: ``release-{service-name}-{env}-{short-sha}``

    Examples::

        release-fourdogs-catalog-trigger-prod-ba5b8fa5  → fourdogs-catalog-trigger
        release-fourdogs-etailpet-sales-trigger-dev-a531b019  → fourdogs-etailpet-sales-trigger
    """
    name = workflow_id
    if name.startswith("release-"):
        name = name[len("release-"):]
    for env_marker in ("-prod-", "-dev-"):
        idx = name.rfind(env_marker)
        if idx != -1:
            name = name[:idx]
            break
    return name


# Attempt count above which SeedSecrets is definitely stuck (not a transient failure).
# At 100s max backoff interval, attempt 10 takes ~7 min total — fast detection, minimal noise.
_SEED_SECRETS_ATTEMPT_THRESHOLD = 10


class TemporalSeedSecretsDetector(BaseDetector):
    """Detect ReleaseWorkflow executions stuck in a SeedSecrets activity failure loop.

    ``SeedSecrets`` invokes a Semaphore task template named ``seed-{service}-secrets``.
    If the template does not exist, the activity fails with a retryable error and
    retries indefinitely (no ``MaxAttempts`` in the retry policy).

    Emits ``temporal-seed-secrets-loop`` (High, remediation_available=True) when:
    - Workflow type is ``ReleaseWorkflow``
    - A pending ``SeedSecrets`` activity has ``attempt > attempt_threshold``
    """

    pattern_id = "temporal-seed-secrets"

    def __init__(
        self,
        temporal_client: TemporalClient,
        attempt_threshold: int = _SEED_SECRETS_ATTEMPT_THRESHOLD,
    ) -> None:
        self._client = temporal_client
        self._attempt_threshold = attempt_threshold

    async def detect(self) -> list[Alert]:
        now = datetime.datetime.now(datetime.UTC)
        alerts: list[Alert] = []

        try:
            workflows = await self._client.list_running_workflows()
        except Exception:
            logger.exception("TemporalSeedSecretsDetector: failed to list running workflows")
            return []

        for wf in workflows:
            if wf.type != "ReleaseWorkflow":
                continue

            try:
                desc = await self._client.describe_workflow(wf.id)
            except Exception:
                logger.warning(
                    "TemporalSeedSecretsDetector: could not describe workflow %s", wf.id
                )
                continue

            for activity in desc.pending_activities or []:
                if activity.activity_type != "SeedSecrets":
                    continue
                if activity.attempt <= self._attempt_threshold:
                    continue

                service_name = _extract_service_name(wf.id)
                template_name = f"seed-{service_name}-secrets"
                elapsed = now - wf.start_time

                failure_hint = ""
                if activity.last_failure is not None:
                    failure_hint = f" Last error: {str(activity.last_failure)[:200]}"

                alerts.append(
                    Alert(
                        pattern="temporal-seed-secrets-loop",
                        severity="high",
                        resource_name=wf.id,
                        resource_namespace=wf.task_queue or "terminus-platform",
                        duration_seconds=elapsed.total_seconds(),
                        diagnosis=(
                            f"ReleaseWorkflow '{wf.id}' is stuck: SeedSecrets has failed "
                            f"{activity.attempt} times. The Semaphore task template "
                            f"'{template_name}' appears to be missing.{failure_hint}"
                        ),
                        recommended_action=(
                            f"Create the Semaphore task template '{template_name}', "
                            "then re-trigger the release pipeline."
                        ),
                        remediation_available=True,
                    )
                )
                break  # one alert per workflow

        return alerts
