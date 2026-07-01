"""Telegram notification service (P011).

A communication layer only: it receives events and delivers them. It contains
no business logic, never calls AI, never decides outcomes. Delivery failures
are logged and swallowed -- the app never stops because Telegram is down.
Every notification is stored for audit.
"""

from __future__ import annotations

import time

import requests

from ..core.enums import NotificationType
from ..core.logging_setup import get_logger
from ..db.services import NotificationService

logger = get_logger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramService:
    def __init__(self, token: str, chat_id: str,
                 notification_service: NotificationService,
                 timeout: int = 15, max_retries: int = 2):
        self.token = token
        self.chat_id = chat_id
        self.store = notification_service
        self.timeout = timeout
        self.max_retries = max_retries
        self.enabled = bool(token and chat_id)
        if not self.enabled:
            logger.warning("Telegram disabled: token/chat_id not configured")

    def send(self, ntype: NotificationType, message: str) -> bool:
        """Send a notification; store it regardless of delivery outcome."""
        full = f"[{ntype.value}]\n{message}"
        sent = False
        if self.enabled:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = requests.post(
                        _API.format(token=self.token),
                        json={"chat_id": self.chat_id, "text": full},
                        timeout=self.timeout,
                    )
                    sent = resp.status_code == 200
                    if sent:
                        break
                    logger.warning("Telegram delivery failed (HTTP %s), attempt %s",
                                   resp.status_code, attempt + 1)
                except requests.RequestException as exc:
                    logger.warning("Telegram delivery error (attempt %s): %s",
                                   attempt + 1, exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))
        try:
            self.store.record(ntype.value, message, sent)
        except Exception as exc:  # noqa: BLE001 - storage must never crash flow
            logger.warning("Could not store notification: %s", exc)
        return sent
