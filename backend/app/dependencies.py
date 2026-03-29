"""
FastAPI dependency injection.

The broker is created ONCE at startup and shared across all requests.
The correct implementation is chosen based on BROKER_MODE env var.

Usage in routes:
    @router.get("/portfolio")
    async def get_portfolio(broker: IBroker = Depends(get_broker)):
        return await broker.get_portfolio_summary()
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends

from app.config import settings, BrokerMode


# Singleton broker and service instances (created in app lifespan)
_broker_instance = None
_trading_engine_instance = None
_portfolio_service_instance = None
_scanner_service_instance = None


def set_broker(broker) -> None:
    global _broker_instance
    _broker_instance = broker


def set_trading_engine(engine) -> None:
    global _trading_engine_instance
    _trading_engine_instance = engine


def set_portfolio_service(service) -> None:
    global _portfolio_service_instance
    _portfolio_service_instance = service


def set_scanner_service(service) -> None:
    global _scanner_service_instance
    _scanner_service_instance = service


async def get_broker():
    if _broker_instance is None:
        raise RuntimeError("Broker not initialized. Is the app lifespan running?")
    return _broker_instance


async def get_trading_engine():
    return _trading_engine_instance


async def get_portfolio_service():
    return _portfolio_service_instance


async def get_scanner_service():
    return _scanner_service_instance


def create_broker():
    """Create the correct broker based on BROKER_MODE."""
    if settings.broker_mode == BrokerMode.PAPER:
        from app.broker.paper_broker import PaperBroker
        return PaperBroker(
            initial_balance=settings.paper_initial_balance,
            slippage_bps=settings.paper_slippage_bps,
        )
    else:
        from app.broker.kalshi_client import KalshiClient
        return KalshiClient(
            base_url=settings.kalshi_base_url,
            api_key=settings.kalshi_api_key,
            private_key_b64=settings.kalshi_private_key_b64,
        )
