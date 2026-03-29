from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from app.dependencies import get_broker
from app.schemas.market import MarketOut, OrderbookOut

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("", response_model=list[MarketOut])
async def list_markets(
    status: str = "active",
    category: Optional[str] = None,
    limit: int = Query(100, le=500),
    broker=Depends(get_broker),
):
    return await broker.get_markets(status=status, category=category, limit=limit)


@router.get("/{ticker}", response_model=MarketOut)
async def get_market(ticker: str, broker=Depends(get_broker)):
    market = await broker.get_market(ticker)
    if not market:
        raise HTTPException(404, f"Market {ticker} not found")
    return market


@router.get("/{ticker}/orderbook", response_model=Optional[OrderbookOut])
async def get_orderbook(ticker: str, broker=Depends(get_broker)):
    return await broker.get_orderbook(ticker)
