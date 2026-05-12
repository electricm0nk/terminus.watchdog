"""Tests for Dockerfile existence and secrets hygiene — Story 1.3."""
from __future__ import annotations

from pathlib import Path


def test_dockerfile_exists() -> None:
    assert Path("Dockerfile").exists(), "Dockerfile must exist in repo root"


def test_dockerignore_exists() -> None:
    assert Path(".dockerignore").exists(), ".dockerignore must exist in repo root"


def test_no_secrets_in_dockerfile() -> None:
    content = Path("Dockerfile").read_text()
    assert "DISCORD_BOT_TOKEN" not in content, "DISCORD_BOT_TOKEN must not be hardcoded in Dockerfile"
    assert "ARGOCD_TOKEN" not in content, "ARGOCD_TOKEN must not be hardcoded in Dockerfile"


def test_no_secrets_in_ci_workflow() -> None:
    ci_path = Path(".github/workflows/ci.yml")
    assert ci_path.exists(), ".github/workflows/ci.yml must exist"
    content = ci_path.read_text()
    assert "DISCORD_BOT_TOKEN" not in content
    assert "ARGOCD_TOKEN" not in content


def test_release_workflow_exists() -> None:
    assert Path(".github/workflows/release.yml").exists(), ".github/workflows/release.yml must exist"
