"""
FastAPI application factory.

Lifespan handler:
1. Creates the broker (paper/demo/live based on BROKER_MODE)
2. Creates all trading strategies
3. Creates trading engine, portfolio service, scanner service
4. Starts background workers (market poller, strategy runner, P&L calculator)
5. Wires WebSocket broadcast callback to trading engine
6. Tears down cleanly on shutdown
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.dependencies import (
    create_broker, set_broker, set_trading_engine,
    set_portfolio_service, set_scanner_service,
)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: setup → yield → teardown."""
    log.info("Starting Kalshi Trading Bot (mode=%s)", settings.broker_mode.value)

    # ── 1. Create broker ──────────────────────────────────────────
    broker = create_broker()
    set_broker(broker)
    log.info("Broker initialized: %s", type(broker).__name__)

    # ── 2. Create strategies ──────────────────────────────────────
    from app.core.strategies.longshot_bias import LongshotBiasStrategy
    from app.core.strategies.market_making import MarketMakingStrategy
    from app.core.strategies.nowcasting import NowcastingStrategy
    from app.core.strategies.cross_market_arb import CrossMarketArbStrategy
    from app.core.strategies.lip_optimizer import LIPOptimizerStrategy

    strategies = [
        LongshotBiasStrategy(),
        MarketMakingStrategy(),
        NowcastingStrategy(),
        CrossMarketArbStrategy(),
        LIPOptimizerStrategy(),
    ]
    # Longshot bias is enabled by default (safest strategy for starting)
    strategies[0].enabled = True

    # ── 3. Create services ────────────────────────────────────────
    from app.services.trading_engine import TradingEngine
    from app.services.portfolio_service import PortfolioService
    from app.services.scanner_service import ScannerService

    trading_engine = TradingEngine(broker)
    for strategy in strategies:
        trading_engine.register_strategy(strategy)

    portfolio_service = PortfolioService(broker)
    scanner_service = ScannerService(broker, strategies)

    set_trading_engine(trading_engine)
    set_portfolio_service(portfolio_service)
    set_scanner_service(scanner_service)

    # Wire WebSocket broadcast to trading engine
    from app.api.ws.feed import manager
    trading_engine.set_ws_callback(manager.broadcast)

    # ── 4. Start background workers ───────────────────────────────
    from app.workers.market_poller import MarketPoller

    market_poller = MarketPoller(broker, poll_interval=settings.market_poll_interval_seconds)

    async def run_market_poller():
        await market_poller.start()

    async def run_strategy_tick():
        while True:
            try:
                signals = await trading_engine.tick()
                if signals:
                    log.info("Strategy tick: %d signals executed", len(signals))
                    # Broadcast portfolio update after each tick
                    summary = await broker.get_portfolio_summary()
                    await manager.broadcast({
                        "type": "portfolio_update",
                        "data": {
                            "cash_balance": summary.cash_balance,
                            "total_equity": summary.total_equity,
                            "unrealized_pnl": summary.unrealized_pnl,
                            "realized_pnl": summary.realized_pnl,
                            "num_positions": summary.num_positions,
                        }
                    })
            except Exception as e:
                log.error("Strategy tick error: %s", e)
            await asyncio.sleep(settings.strategy_tick_interval_seconds)

    async def run_pnl_calculator():
        while True:
            try:
                await portfolio_service.snapshot()
                summary = await broker.get_portfolio_summary()
                await manager.broadcast({
                    "type": "portfolio_update",
                    "data": {
                        "cash_balance": summary.cash_balance,
                        "total_equity": summary.total_equity,
                        "unrealized_pnl": summary.unrealized_pnl,
                        "realized_pnl": summary.realized_pnl,
                        "num_positions": summary.num_positions,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                })
            except Exception as e:
                log.error("P&L calculator error: %s", e)
            await asyncio.sleep(settings.pnl_calc_interval_seconds)

    # Start all workers as background tasks
    tasks = [
        asyncio.create_task(run_market_poller(), name="market_poller"),
        asyncio.create_task(run_strategy_tick(), name="strategy_tick"),
        asyncio.create_task(run_pnl_calculator(), name="pnl_calculator"),
    ]

    log.info("All workers started. Bot is running.")

    yield  # Application runs here

    # ── 5. Teardown ───────────────────────────────────────────────
    log.info("Shutting down Kalshi Trading Bot...")
    market_poller.stop()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("Shutdown complete.")


# ── FastAPI app ────────────────────────────────────────────────────
app = FastAPI(
    title="Kalshi Trading Bot",
    description="World-class prediction market trading bot",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
from app.api.v1.router import router as api_router
from app.api.ws.feed import router as ws_router

app.include_router(api_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "broker_mode": settings.broker_mode.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
