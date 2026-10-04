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

_API = "https://api.telegram.org/bot{token}/{method}"


def telegram_text_decision(text: str | None) -> str | None:
    """Exact approval commands only.

    The whole message must be ``Proceed`` or ``Reject`` (case-insensitive).
    ``yes``, ``ok``, ``go``, ``submit``, and ``approve`` do not authorize
    anything.
    """
    cleaned = (text or "").strip().lower().strip(".,!")
    if cleaned == "proceed":
        return "proceed"
    if cleaned == "reject":
        return "reject"
    return None


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
        self._update_offset = 0
        self._offset_settings = None
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
                        _API.format(token=self.token, method="sendMessage"),
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

    def attach_offset_store(self, settings) -> None:
        """Remember the Telegram update cursor in SQLite across restarts."""
        self._offset_settings = settings
        raw = settings.get("telegram_update_offset") if settings else None
        if raw and str(raw).isdigit():
            self._update_offset = int(raw)

    @staticmethod
    def _classify_reply(text: str) -> str | None:
        return telegram_text_decision(text)

    def poll_once(self) -> str | None:
        """Read one new reply, if any. Does not block."""
        if not self.enabled:
            return None
        return self._classify_reply(self._next_reply() or "")

    def wait_for_reply(self, timeout_seconds: int = 900, poll_seconds: int = 3) -> str:
        """Block until this chat replies Proceed or Reject.

        Returns ``proceed``, ``reject``, ``timeout``, or ``unavailable`` when
        Telegram is not configured. Does not submit anything by itself.
        """
        if not self.enabled:
            return "unavailable"
        deadline = time.time() + max(1, timeout_seconds)
        while time.time() < deadline:
            decision = self._classify_reply(self._next_reply() or "")
            if decision:
                return decision
            time.sleep(poll_seconds)
        return "timeout"

    def _next_reply(self) -> str | None:
        try:
            resp = requests.get(
                _API.format(token=self.token, method="getUpdates"),
                params={"timeout": 1, "offset": self._update_offset},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return None
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Telegram poll failed: %s", exc)
            return None
        found = None
        for update in payload.get("result") or []:
            self._update_offset = max(
                self._update_offset, int(update.get("update_id", 0)) + 1)
            if self._offset_settings is not None:
                try:
                    self._offset_settings.set(
                        "telegram_update_offset", str(self._update_offset))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not store Telegram offset: %s", exc)
            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat") or {}
            if str(chat.get("id", "")) != str(self.chat_id):
                continue
            found = message.get("text") or ""
        return found
