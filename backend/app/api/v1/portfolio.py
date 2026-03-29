from fastapi import APIRouter, Depends, Query
from datetime import datetime, timezone, timedelta
from app.dependencies import get_broker, get_portfolio_service
from app.schemas.portfolio import PortfolioSummary, PortfolioMetrics, PortfolioHistory, EquityPoint

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummary)
async def get_summary(broker=Depends(get_broker)):
    return await broker.get_portfolio_summary()


@router.get("/metrics", response_model=PortfolioMetrics)
async def get_metrics(
    period_days: int = Query(30, ge=1, le=365),
    portfolio_service=Depends(get_portfolio_service),
):
    if portfolio_service is None:
        return PortfolioMetrics()
    return await portfolio_service.compute_metrics(period_days=period_days)


@router.get("/history", response_model=PortfolioHistory)
async def get_history(
    period_days: int = Query(30, ge=1, le=365),
    broker=Depends(get_broker),
    portfolio_service=Depends(get_portfolio_service),
):
    summary = await broker.get_portfolio_summary()
    if portfolio_service is None:
        return PortfolioHistory(
            broker_mode=summary.broker_mode,
            points=[EquityPoint(timestamp=datetime.now(timezone.utc), total_equity=summary.total_equity)],
            initial_equity=summary.total_equity,
        )

    since = datetime.now(timezone.utc) - timedelta(days=period_days)
    history = portfolio_service.get_equity_history(since=since)
    points = [EquityPoint(timestamp=ts, total_equity=eq) for ts, eq in history]
    initial = history[0][1] if history else summary.total_equity

    return PortfolioHistory(
        broker_mode=summary.broker_mode,
        points=points,
        initial_equity=initial,
    )
