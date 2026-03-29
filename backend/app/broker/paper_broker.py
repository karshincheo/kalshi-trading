"""
PaperBroker — Full paper trading simulator implementing IBroker.

Fill simulation rules:
  - Market orders: fill immediately at (bid+ask)/2 + slippage
  - Limit orders: fill when a tick() sees the market cross the limit price
  - Slippage model: configurable basis points spread applied adversarially
  - P&L: marked to mid price on each tick() call

Position tracking:
  - YES and NO are tracked separately per ticker
  - Avg cost uses weighted average on partial fills
  - Realized P&L computed on FIFO basis when positions are reduced

This broker intentionally mimics the Kalshi REST API response shapes
so switching to KalshiClient requires zero changes in callers.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.schemas.market import MarketOut, OrderbookOut
from app.schemas.order import OrderRequest, OrderOut, FillOut
from app.schemas.position import PositionOut
from app.schemas.portfolio import PortfolioSummary


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _PaperPosition:
    def __init__(self, ticker: str, side: str, count: int, avg_cost: float, strategy: Optional[str]):
        self.ticker = ticker
        self.contract_side = side
        self.count = count
        self.avg_cost = avg_cost
        self.realized_pnl = 0.0
        self.current_price: Optional[float] = None
        self.strategy_name = strategy
        self.created_at = _now()
        self.updated_at = _now()

    def mark(self, price: float) -> None:
        self.current_price = price
        self.updated_at = _now()

    @property
    def unrealized_pnl(self) -> Optional[float]:
        if self.current_price is None:
            return None
        # Each contract pays $1 if correct, $0 if wrong.
        # Cost in dollars (prices are in [0,1] range).
        return (self.current_price - self.avg_cost) * self.count

    def reduce(self, count: int, exit_price: float) -> float:
        """Reduce position by count contracts, return realized PnL."""
        if count > self.count:
            count = self.count
        pnl = (exit_price - self.avg_cost) * count
        self.realized_pnl += pnl
        self.count -= count
        self.updated_at = _now()
        return pnl


class _PaperOrder:
    def __init__(self, req: OrderRequest, order_id: str, broker_mode: str):
        self.id = order_id
        self.broker_mode = broker_mode
        self.ticker = req.ticker
        self.action = req.action
        # buy_yes/buy_no → side=buy; sell_yes/sell_no → side=sell
        self.side = "buy" if req.action.startswith("buy") else "sell"
        self.order_type = req.order_type
        self.count = req.count
        self.limit_price = req.limit_price
        self.filled_count = 0
        self.avg_fill_price: Optional[float] = None
        self.status = "open"
        self.strategy_name = req.strategy_name
        self.notes = req.notes
        self.created_at = _now()
        self.updated_at = _now()

    def to_out(self, signal_edge: Optional[float] = None, kelly_fraction: Optional[float] = None) -> OrderOut:
        return OrderOut(
            id=self.id,
            broker_mode=self.broker_mode,
            ticker=self.ticker,
            side=self.side,
            order_type=self.order_type,
            action=self.action,
            count=self.count,
            limit_price=self.limit_price,
            filled_count=self.filled_count,
            avg_fill_price=self.avg_fill_price,
            status=self.status,
            strategy_name=self.strategy_name,
            signal_edge=signal_edge,
            kelly_fraction=kelly_fraction,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class PaperBroker:
    """
    Paper trading simulator.
    Thread-safe for asyncio (single event loop — no explicit locking needed).
    """

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        slippage_bps: float = 5.0,
    ) -> None:
        self._initial_balance = initial_balance
        self._cash = initial_balance
        self._slippage_bps = slippage_bps
        self._positions: dict[str, _PaperPosition] = {}  # key: f"{ticker}_{side}"
        self._orders: dict[str, _PaperOrder] = {}
        self._fills: list[FillOut] = []
        self._market_cache: dict[str, MarketOut] = {}

    @property
    def mode(self) -> str:
        return "paper"

    # ── Market data helpers ────────────────────────────────────

    def update_market(self, market: MarketOut) -> None:
        """Called by market_poller to keep prices current."""
        self._market_cache[market.ticker] = market
        # Mark open positions to current price
        for pos in self._positions.values():
            if pos.ticker == market.ticker:
                mid = market.yes_mid or (
                    ((market.yes_bid or 0) + (market.yes_ask or 1)) / 2
                )
                if pos.contract_side == "yes":
                    pos.mark(mid)
                else:
                    pos.mark(1.0 - mid)

    # ── IBroker implementation ─────────────────────────────────

    async def get_balance(self) -> float:
        return self._cash

    async def get_portfolio_summary(self) -> PortfolioSummary:
        position_value = sum(
            (p.current_price or p.avg_cost) * p.count
            for p in self._positions.values()
            if p.count > 0
        )
        total_equity = self._cash + position_value
        unrealized = sum(
            (p.unrealized_pnl or 0) for p in self._positions.values() if p.count > 0
        )
        realized = sum(p.realized_pnl for p in self._positions.values())
        return PortfolioSummary(
            broker_mode="paper",
            cash_balance=self._cash,
            position_value=position_value,
            total_equity=total_equity,
            unrealized_pnl=unrealized,
            realized_pnl=realized,
            num_positions=len([p for p in self._positions.values() if p.count > 0]),
            total_return_pct=(total_equity - self._initial_balance) / self._initial_balance,
            timestamp=_now(),
        )

    async def get_positions(self) -> list[PositionOut]:
        result = []
        for i, pos in enumerate(self._positions.values()):
            if pos.count > 0:
                result.append(PositionOut(
                    id=i,
                    broker_mode="paper",
                    ticker=pos.ticker,
                    contract_side=pos.contract_side,
                    count=pos.count,
                    avg_cost=pos.avg_cost,
                    current_price=pos.current_price,
                    unrealized_pnl=pos.unrealized_pnl,
                    realized_pnl=pos.realized_pnl,
                    strategy_name=pos.strategy_name,
                    created_at=pos.created_at,
                    updated_at=pos.updated_at,
                ))
        return result

    async def get_market(self, ticker: str) -> Optional[MarketOut]:
        return self._market_cache.get(ticker)

    async def get_markets(
        self,
        status: str = "active",
        category: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> list[MarketOut]:
        markets = list(self._market_cache.values())
        if status:
            markets = [m for m in markets if m.status == status]
        if category:
            markets = [m for m in markets if m.category == category]
        return markets[:limit]

    async def get_orderbook(self, ticker: str) -> Optional[OrderbookOut]:
        # Paper broker doesn't have real orderbooks; return None
        return None

    async def place_order(self, req: OrderRequest) -> OrderOut:
        order_id = str(uuid.uuid4())
        order = _PaperOrder(req, order_id, "paper")

        if req.order_type == "market":
            filled = self._fill_market_order(order)
            if filled:
                order.status = "filled"
            else:
                order.status = "cancelled"
        else:
            # Limit order: queue it, fill on next tick
            order.status = "open"
            self._orders[order_id] = order

        return order.to_out()

    def _fill_market_order(self, order: _PaperOrder) -> bool:
        """Attempt to fill a market order at mid + slippage. Returns True if filled."""
        market = self._market_cache.get(order.ticker)
        if market is None:
            return False

        yes_mid = market.yes_mid or (
            ((market.yes_bid or 0) + (market.yes_ask or 1)) / 2
        )
        slippage = self._slippage_bps / 10_000.0

        # Determine fill price based on action and apply adverse slippage
        if order.action == "buy_yes":
            fill_price = min(1.0, yes_mid + slippage)
            position_side = "yes"
        elif order.action == "buy_no":
            fill_price = min(1.0, (1.0 - yes_mid) + slippage)
            position_side = "no"
        elif order.action == "sell_yes":
            fill_price = max(0.0, yes_mid - slippage)
            position_side = "yes"
        else:  # sell_no
            fill_price = max(0.0, (1.0 - yes_mid) - slippage)
            position_side = "no"

        cost = fill_price * order.count  # in dollars
        is_buy = order.action.startswith("buy")

        if is_buy:
            if cost > self._cash:
                order.count = max(0, int(self._cash / fill_price))
                if order.count == 0:
                    return False
                cost = fill_price * order.count

            self._cash -= cost
            pos_key = f"{order.ticker}_{position_side}"
            if pos_key in self._positions and self._positions[pos_key].count > 0:
                existing = self._positions[pos_key]
                # Weighted average cost
                total_count = existing.count + order.count
                existing.avg_cost = (
                    (existing.avg_cost * existing.count + fill_price * order.count)
                    / total_count
                )
                existing.count = total_count
                existing.updated_at = _now()
            else:
                self._positions[pos_key] = _PaperPosition(
                    order.ticker, position_side, order.count, fill_price, order.strategy_name
                )
        else:
            # Selling: reduce position, return cash
            pos_key = f"{order.ticker}_{position_side}"
            pos = self._positions.get(pos_key)
            if pos is None or pos.count == 0:
                return False
            sell_count = min(order.count, pos.count)
            realized = pos.reduce(sell_count, fill_price)
            self._cash += fill_price * sell_count
            order.count = sell_count

        # Record fill
        fill_id = str(uuid.uuid4())
        self._fills.append(FillOut(
            id=fill_id,
            order_id=order.id,
            ticker=order.ticker,
            side=order.side,
            action=order.action,
            count=order.count,
            price=fill_price,
            fee=0.0,
            strategy_name=order.strategy_name,
            broker_mode="paper",
            filled_at=_now(),
        ))

        order.filled_count = order.count
        order.avg_fill_price = fill_price
        return True

    def tick(self) -> None:
        """Called by strategy_runner on each interval. Fills pending limit orders."""
        for order_id, order in list(self._orders.items()):
            if order.status != "open":
                continue
            market = self._market_cache.get(order.ticker)
            if market is None:
                continue
            yes_mid = market.yes_mid or (
                ((market.yes_bid or 0) + (market.yes_ask or 1)) / 2
            )

            should_fill = False
            if order.action == "buy_yes" and order.limit_price and yes_mid <= order.limit_price:
                should_fill = True
            elif order.action == "buy_no" and order.limit_price:
                no_mid = 1.0 - yes_mid
                if no_mid <= order.limit_price:
                    should_fill = True
            elif order.action in ("sell_yes", "sell_no") and order.limit_price:
                price_to_check = yes_mid if order.action == "sell_yes" else (1.0 - yes_mid)
                if price_to_check >= order.limit_price:
                    should_fill = True

            if should_fill:
                filled = self._fill_market_order(order)
                order.status = "filled" if filled else "cancelled"

    async def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order and order.status == "open":
            order.status = "cancelled"
            return True
        return False

    async def get_order(self, order_id: str) -> Optional[OrderOut]:
        order = self._orders.get(order_id)
        return order.to_out() if order else None

    async def get_orders(
        self,
        status: Optional[str] = None,
        ticker: Optional[str] = None,
        limit: int = 50,
    ) -> list[OrderOut]:
        orders = list(self._orders.values())
        if status:
            orders = [o for o in orders if o.status == status]
        if ticker:
            orders = [o for o in orders if o.ticker == ticker]
        return [o.to_out() for o in orders[-limit:]]

    async def get_fills(
        self,
        ticker: Optional[str] = None,
        limit: int = 50,
    ) -> list[FillOut]:
        fills = self._fills
        if ticker:
            fills = [f for f in fills if f.ticker == ticker]
        return fills[-limit:]
