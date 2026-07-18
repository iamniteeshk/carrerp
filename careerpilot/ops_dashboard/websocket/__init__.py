"""WebSocket live updates for Mission Control."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..activity import FEED
from ..runtime import HUB

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    last_ts = ""
    try:
        while True:
            events = FEED.recent(limit=30, after_ts=last_ts)
            if events:
                last_ts = events[0]["ts"]
            payload = {
                "type": "tick",
                "phase": HUB.current_phase(),
                "paused": HUB.paused,
                "live": HUB.live_status(),
                "preview": HUB.preview_meta(),
                "events": list(reversed(events)) if events else [],
                "alerts": FEED.alerts(10),
                "uptime_seconds": round(HUB.uptime_seconds, 1),
            }
            await websocket.send_text(json.dumps(payload, default=str))
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
