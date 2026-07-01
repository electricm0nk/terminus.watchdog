from __future__ import annotations

from watchdog.config import Settings


def _set_required_env(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_ALERTS_CHANNEL_ID", "123456789")
    monkeypatch.setenv("DISCORD_INFO_CHANNEL_ID", "987654321")
    monkeypatch.setenv("ARGOCD_URL", "https://argocd.example.internal")
    monkeypatch.setenv("ARGOCD_TOKEN", "argocd-token")
    monkeypatch.setenv("TEMPORAL_HOST", "temporal.example.internal:7233")


def test_discord_bot_token_is_trimmed_before_use(monkeypatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "  discord-bot-token\n")

    settings = Settings()

    assert settings.discord_bot_token == "discord-bot-token"
