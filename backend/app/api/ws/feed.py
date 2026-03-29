"""
WebSocket feed — real-time push from backend to frontend.

Messages broadcast to all connected clients:
  - portfolio_update: new portfolio snapshot
  - order_placed: new order placed by trading engine
  - order_update: order status changed
  - signal: new trading signal generated
  - market_tick: market price updated
  - circuit_breaker: halt event
  - halt: trading halted

Frontend connects to ws://localhost:8000/api/ws/feed
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)
router = APIRouter()

# Global connection manager
_connections: set[WebSocket] = set()


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        log.info("WS client connected. Total: %d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        log.info("WS client disconnected. Total: %d", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        if not self._connections:
            return
        message["timestamp"] = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(message)
        dead = set()
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)


# Singleton manager — imported by trading_engine for broadcasting
manager = ConnectionManager()


@router.websocket("/api/ws/feed")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send initial connection acknowledgement
        await ws.send_text(json.dumps({
            "type": "connected",
            "message": "Kalshi Trading Bot WebSocket",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

        # Keep connection alive, handle incoming messages
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                msg = json.loads(data)
                # Handle ping
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send heartbeat
                await ws.send_text(json.dumps({"type": "heartbeat"}))
            except WebSocketDisconnect:
                break
            except Exception:
                break
    finally:
        manager.disconnect(ws)
