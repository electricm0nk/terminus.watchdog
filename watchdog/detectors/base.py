"""BaseDetector — abstract base class for all watchdog detectors."""

from __future__ import annotations

from abc import ABC, abstractmethod

from watchdog.models import Alert


class BaseDetector(ABC):
    """All detectors implement this interface.

    Each detector polls a single system (ArgoCD, Temporal, etc.) and
    returns a (possibly empty) list of Alert instances describing
    detected conditions.
    """

    @property
    @abstractmethod
    def pattern_id(self) -> str:
        """Unique identifier for the pattern this detector checks."""
        ...

    @abstractmethod
    async def detect(self) -> list[Alert]:
        """Run detection and return any active alerts."""
        ...
