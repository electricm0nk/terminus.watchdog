"""Discord bot — Gateway-mode WatchdogBot — Story 2.2."""
from __future__ import annotations

import logging

import discord

from watchdog.discord.alerts import format_alert_embed, is_quiet_hours
from watchdog.models import Alert
from watchdog.state import WatchdogState

log = logging.getLogger(__name__)


class WatchdogBot(discord.Client):
    """discord.py Client in Gateway mode.

    Maintains a persistent WebSocket connection to Discord.
    No public HTTPS ingress required for alert posting.
    """

    def __init__(
        self,
        alerts_channel_id: int,
        info_channel_id: int,
        ops_user_ids: list[str],
    ) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self._alerts_channel_id = alerts_channel_id
        self._info_channel_id = info_channel_id
        self._ops_user_ids = ops_user_ids

    async def on_ready(self) -> None:
        log.info("WatchdogBot connected: %s — %d guild(s)", self.user, len(self.guilds))

    async def post_alert(self, alert: Alert, state: WatchdogState) -> int:
        """Post a formatted alert embed to the appropriate Discord channel.

        Returns the Discord message_id of the posted message.

        Channel routing:
        - High → DISCORD_ALERTS_CHANNEL_ID
        - Medium/Informational → DISCORD_INFO_CHANNEL_ID

        Mention logic:
        - @mention ops user IDs for High severity alerts unless quiet hours
          (or alert.bypass_quiet_hours is True)
        """
        channel_id = (
            self._alerts_channel_id if alert.severity == "high" else self._info_channel_id
        )
        channel = self.get_channel(channel_id)
        if channel is None:
            channel = await self.fetch_channel(channel_id)

        embed = format_alert_embed(alert)

        content: str | None = None
        if alert.severity == "high" and self._ops_user_ids:
            if alert.bypass_quiet_hours or not is_quiet_hours():
                mentions = " ".join(f"<@{uid}>" for uid in self._ops_user_ids)
                content = mentions

        if not isinstance(channel, discord.TextChannel):
            raise TypeError(f"Channel {channel_id} is not a TextChannel")

        message = await channel.send(content=content, embed=embed)
        return message.id

    async def post_info(self, message: str) -> None:
        """Post a plain informational message to the platform-info channel.

        Used for source-degradation warnings (FR35) and heartbeats.
        Never raises — logs errors silently to avoid crashing the detection loop.
        """
        try:
            channel = self.get_channel(self._info_channel_id)
            if channel is None:
                channel = await self.fetch_channel(self._info_channel_id)
            if not isinstance(channel, discord.TextChannel):
                log.error("Info channel %d is not a TextChannel — cannot post", self._info_channel_id)
                return
            await channel.send(content=message)
        except Exception as exc:
            log.error("post_info failed: %s", exc)
