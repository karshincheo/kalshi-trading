"""
IBroker Protocol — the core contract every broker implementation must satisfy.

Using Python's structural Protocol (PEP 544) instead of ABC:
- KalshiClient, PaperBroker, and any mock can satisfy this without inheriting from it
- Zero import-time coupling between strategies and broker implementations
- Trivially mockable in tests (any object with the right methods works)

IMPORTANT: All strategies and services must call IBroker methods only.
They must NEVER import KalshiClient or PaperBroker directly.
The correct implementation is injected via dependencies.py.
"""
from __future__ import annotations
from typing import Protocol, Optional, runtime_checkable
from app.schemas.market import MarketOut, OrderbookOut
from app.schemas.order import OrderRequest, OrderOut, FillOut
from app.schemas.position import PositionOut
from app.schemas.portfolio import PortfolioSummary


@runtime_checkable
class IBroker(Protocol):
    """Interface contract for all broker implementations."""

    @property
    def mode(self) -> str:
        """Returns 'paper', 'demo', or 'live'."""
        ...

    async def get_balance(self) -> float:
        """Returns current cash balance in dollars."""
        ...

    async def get_portfolio_summary(self) -> PortfolioSummary:
        """Returns full portfolio summary including positions."""
        ...

    async def get_positions(self) -> list[PositionOut]:
        """Returns all open positions."""
        ...

    async def get_market(self, ticker: str) -> Optional[MarketOut]:
        """Returns current market snapshot. None if not found."""
        ...

    async def get_markets(
        self,
        status: str = "active",
        category: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> list[MarketOut]:
        """Returns list of markets matching filters."""
        ...

    async def get_orderbook(self, ticker: str) -> Optional[OrderbookOut]:
        """Returns current L2 orderbook for market."""
        ...

    async def place_order(self, req: OrderRequest) -> OrderOut:
        """Places an order. Returns order with fill status."""
        ...

    async def cancel_order(self, order_id: str) -> bool:
        """Cancels an open order. Returns True if successful."""
        ...

    async def get_order(self, order_id: str) -> Optional[OrderOut]:
        """Returns order status."""
        ...

    async def get_orders(
        self,
        status: Optional[str] = None,
        ticker: Optional[str] = None,
        limit: int = 50,
    ) -> list[OrderOut]:
        """Returns list of orders."""
        ...

    async def get_fills(
        self,
        ticker: Optional[str] = None,
        limit: int = 50,
    ) -> list[FillOut]:
        """Returns list of trade fills."""
        ...
