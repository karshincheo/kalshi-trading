"""
KalshiClient — Wraps the Kalshi REST API (demo and live).

Uses httpx for async HTTP. Authentication uses RSA-PSS signature
(Kalshi's API key auth scheme).

When BROKER_MODE=demo: connects to demo-trading-api.kalshi.co
When BROKER_MODE=live: connects to trading-api.kalshi.com

Public market data endpoints (no auth required):
  GET /markets, GET /markets/{ticker}, GET /markets/{ticker}/orderbook
  These are used even in paper mode for market data.
"""
from __future__ import annotations

import base64
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import settings
from app.schemas.market import MarketOut, OrderbookOut, OrderbookLevel
from app.schemas.order import OrderRequest, OrderOut, FillOut
from app.schemas.position import PositionOut
from app.schemas.portfolio import PortfolioSummary

# Public base URL for unauthenticated market data (works in paper mode too)
PUBLIC_BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"


class KalshiClient:
    """
    Async Kalshi API client implementing IBroker.

    For paper/demo mode without keys: only public endpoints work.
    For demo/live mode with keys: all endpoints work.
    """

    def __init__(self, base_url: str, api_key: Optional[str] = None, private_key_b64: Optional[str] = None) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._private_key_b64 = private_key_b64
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=15.0,
            headers={"Content-Type": "application/json"},
        )

    @property
    def mode(self) -> str:
        return settings.broker_mode.value

    def _auth_headers(self, method: str, path: str) -> dict:
        """Generate RSA-PSS auth headers for Kalshi API."""
        if not self._api_key:
            return {}
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.backends import default_backend

            ts = str(int(time.time() * 1000))
            msg = ts + method.upper() + path
            key_bytes = base64.b64decode(self._private_key_b64 or "")
            private_key = serialization.load_pem_private_key(
                key_bytes, password=None, backend=default_backend()
            )
            signature = private_key.sign(
                msg.encode("utf-8"),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
            return {
                "KALSHI-ACCESS-KEY": self._api_key,
                "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            }
        except Exception:
            return {}

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        headers = self._auth_headers("GET", path)
        resp = await self._client.get(path, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict) -> dict:
        headers = self._auth_headers("POST", path)
        resp = await self._client.post(path, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str) -> dict:
        headers = self._auth_headers("DELETE", path)
        resp = await self._client.delete(path, headers=headers)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _parse_market(m: dict) -> MarketOut:
        yes_bid = m.get("yes_bid") or m.get("yes_bid_price")
        yes_ask = m.get("yes_ask") or m.get("yes_ask_price")
        if yes_bid is not None:
            yes_bid = yes_bid / 100  # Kalshi returns cents, we use 0-1
        if yes_ask is not None:
            yes_ask = yes_ask / 100
        close_time = m.get("close_time") or m.get("expiration_time")
        return MarketOut(
            ticker=m.get("ticker", ""),
            event_ticker=m.get("event_ticker", ""),
            title=m.get("title", ""),
            subtitle=m.get("subtitle"),
            category=m.get("category"),
            status=m.get("status", "active"),
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            yes_mid=((yes_bid or 0) + (yes_ask or 1)) / 2 if yes_bid and yes_ask else None,
            last_price=(m.get("last_price") or 0) / 100 if m.get("last_price") else None,
            volume_24h=m.get("volume_24h") or m.get("volume"),
            open_interest=m.get("open_interest"),
            close_time=datetime.fromisoformat(close_time.replace("Z", "+00:00")) if close_time else None,
            result=m.get("result"),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    async def get_markets(
        self,
        status: str = "active",
        category: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> list[MarketOut]:
        # Use public base URL for market data (no auth needed)
        async with httpx.AsyncClient(base_url=PUBLIC_BASE_URL, timeout=15.0) as client:
            params: dict = {"limit": limit, "status": status}
            if category:
                params["category"] = category
            if cursor:
                params["cursor"] = cursor
            resp = await client.get("/markets", params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
            markets_data = data.get("markets", [])
            return [self._parse_market(m) for m in markets_data]

    async def get_market(self, ticker: str) -> Optional[MarketOut]:
        async with httpx.AsyncClient(base_url=PUBLIC_BASE_URL, timeout=15.0) as client:
            resp = await client.get(f"/markets/{ticker}")
            if resp.status_code != 200:
                return None
            data = resp.json()
            market_data = data.get("market", data)
            return self._parse_market(market_data)

    async def get_orderbook(self, ticker: str) -> Optional[OrderbookOut]:
        async with httpx.AsyncClient(base_url=PUBLIC_BASE_URL, timeout=15.0) as client:
            resp = await client.get(f"/markets/{ticker}/orderbook")
            if resp.status_code != 200:
                return None
            data = resp.json()
            ob = data.get("orderbook", data)
            bids = [OrderbookLevel(price=b[0] / 100, size=b[1]) for b in ob.get("yes", [])]
            asks = [OrderbookLevel(price=a[0] / 100, size=a[1]) for a in ob.get("no", [])]
            return OrderbookOut(
                ticker=ticker,
                timestamp=datetime.now(timezone.utc),
                bids=bids,
                asks=asks,
            )

    async def get_balance(self) -> float:
        data = await self._get("/portfolio/balance")
        return (data.get("balance", 0)) / 100  # cents to dollars

    async def get_portfolio_summary(self) -> PortfolioSummary:
        balance = await self.get_balance()
        positions = await self.get_positions()
        position_value = sum((p.current_price or p.avg_cost) * p.count for p in positions)
        return PortfolioSummary(
            broker_mode=self.mode,
            cash_balance=balance,
            position_value=position_value,
            total_equity=balance + position_value,
            unrealized_pnl=sum(p.unrealized_pnl or 0 for p in positions),
            realized_pnl=sum(p.realized_pnl for p in positions),
            num_positions=len(positions),
            timestamp=datetime.now(timezone.utc),
        )

    async def get_positions(self) -> list[PositionOut]:
        data = await self._get("/portfolio/positions")
        positions = data.get("market_positions", [])
        result = []
        for i, p in enumerate(positions):
            result.append(PositionOut(
                id=i,
                broker_mode=self.mode,
                ticker=p.get("ticker", ""),
                contract_side="yes" if p.get("position", 0) > 0 else "no",
                count=abs(p.get("position", 0)),
                avg_cost=(p.get("market_exposure", 0) / max(1, abs(p.get("position", 1)))) / 100,
                realized_pnl=(p.get("realized_pnl", 0)) / 100,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ))
        return result

    async def place_order(self, req: OrderRequest) -> OrderOut:
        # Map action to Kalshi API fields
        side_map = {"buy_yes": ("buy", "yes"), "buy_no": ("buy", "no"),
                    "sell_yes": ("sell", "yes"), "sell_no": ("sell", "no")}
        side, yes_no = side_map[req.action]
        body = {
            "ticker": req.ticker,
            "action": side,
            "side": yes_no,
            "count": req.count,
            "type": req.order_type,
            "client_order_id": str(uuid.uuid4()),
        }
        if req.limit_price is not None:
            body["yes_price"] = int(req.limit_price * 100)

        data = await self._post("/portfolio/orders", body)
        order = data.get("order", data)
        return OrderOut(
            id=order.get("order_id", str(uuid.uuid4())),
            broker_mode=self.mode,
            ticker=req.ticker,
            side=side,
            order_type=req.order_type,
            action=req.action,
            count=req.count,
            limit_price=req.limit_price,
            filled_count=order.get("count_filled", 0),
            avg_fill_price=(order.get("avg_price", 0) or 0) / 100,
            status=order.get("status", "open"),
            strategy_name=req.strategy_name,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    async def cancel_order(self, order_id: str) -> bool:
        try:
            await self._delete(f"/portfolio/orders/{order_id}")
            return True
        except Exception:
            return False

    async def get_order(self, order_id: str) -> Optional[OrderOut]:
        try:
            data = await self._get(f"/portfolio/orders/{order_id}")
            order = data.get("order", data)
            return OrderOut(
                id=order.get("order_id", order_id),
                broker_mode=self.mode,
                ticker=order.get("ticker", ""),
                side=order.get("action", "buy"),
                order_type=order.get("type", "market"),
                action=f"{order.get('action', 'buy')}_{order.get('side', 'yes')}",
                count=order.get("count", 0),
                filled_count=order.get("count_filled", 0),
                status=order.get("status", "open"),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        except Exception:
            return None

    async def get_orders(
        self,
        status: Optional[str] = None,
        ticker: Optional[str] = None,
        limit: int = 50,
    ) -> list[OrderOut]:
        params: dict = {"limit": limit}
        if status:
            params["status"] = status
        if ticker:
            params["ticker"] = ticker
        try:
            data = await self._get("/portfolio/orders", params=params)
            orders = data.get("orders", [])
            return [OrderOut(
                id=o.get("order_id", ""),
                broker_mode=self.mode,
                ticker=o.get("ticker", ""),
                side=o.get("action", "buy"),
                order_type=o.get("type", "market"),
                action=f"{o.get('action', 'buy')}_{o.get('side', 'yes')}",
                count=o.get("count", 0),
                filled_count=o.get("count_filled", 0),
                status=o.get("status", "open"),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ) for o in orders]
        except Exception:
            return []

    async def get_fills(self, ticker: Optional[str] = None, limit: int = 50) -> list[FillOut]:
        params: dict = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        try:
            data = await self._get("/portfolio/fills", params=params)
            fills = data.get("fills", [])
            return [FillOut(
                id=f.get("fill_id", str(uuid.uuid4())),
                order_id=f.get("order_id", ""),
                ticker=f.get("ticker", ""),
                side=f.get("action", "buy"),
                action=f"{f.get('action', 'buy')}_{f.get('side', 'yes')}",
                count=f.get("count", 0),
                price=(f.get("yes_price", 0) or 0) / 100,
                fee=(f.get("fees", 0) or 0) / 100,
                broker_mode=self.mode,
                filled_at=datetime.now(timezone.utc),
            ) for f in fills]
        except Exception:
            return []

    async def close(self) -> None:
        await self._client.aclose()
