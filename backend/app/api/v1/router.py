from fastapi import APIRouter
from app.api.v1 import markets, orders, positions, portfolio, strategies, scanner, backtest, settings_router

router = APIRouter(prefix="/api/v1")

router.include_router(markets.router)
router.include_router(orders.router)
router.include_router(positions.router)
router.include_router(portfolio.router)
router.include_router(strategies.router)
router.include_router(scanner.router)
router.include_router(backtest.router)
router.include_router(settings_router.router)
