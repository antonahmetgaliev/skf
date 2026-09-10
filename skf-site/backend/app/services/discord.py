"""Discord webhook notifications.

Currently used only for new-community requests filed from the calendar page.
The webhook is bound to a single channel at creation time, so the channel it
points at is the only thing deciding who sees these messages.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_EMBED_COLOUR = 0xF5BF24  # SKF gold


class DiscordNotConfigured(RuntimeError):
    """Raised when no webhook URL is configured for the server."""


class DiscordSendFailed(RuntimeError):
    """Raised when Discord rejected the webhook call."""


async def send_community_request(
    *,
    name: str,
    description: str,
    discord_url: str | None,
    user: User,
) -> None:
    """POST a new-community request to the configured Discord webhook.

    The requester is identified from *user* (their session), never from the
    submitted payload.
    """
    webhook_url = settings.discord_community_request_webhook_url
    if not webhook_url:
        raise DiscordNotConfigured

    nickname = user.guild_nickname or user.display_name or user.username
    requested_by = f"{user.username} ({nickname})" if nickname != user.username else user.username

    payload = {
        # Suppress every mention: the fields below carry user-supplied text, so a
        # community named "@everyone" must not be able to ping anyone.
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "New community request",
                "description": description,
                "color": _EMBED_COLOUR,
                "fields": [
                    {"name": "Community", "value": name, "inline": False},
                    {"name": "Discord", "value": discord_url or "—", "inline": False},
                    {"name": "Requested by", "value": requested_by, "inline": True},
                    {"name": "Discord ID", "value": str(user.discord_id), "inline": True},
                ],
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(webhook_url, json=payload)
    except httpx.HTTPError as exc:
        # Never log the webhook URL itself — it is a credential.
        logger.warning("Community request webhook call failed: %s", type(exc).__name__)
        raise DiscordSendFailed from exc

    # Discord returns 204 No Content on success.
    if response.status_code not in (200, 204):
        logger.warning(
            "Community request webhook rejected (status %s)", response.status_code
        )
        raise DiscordSendFailed
