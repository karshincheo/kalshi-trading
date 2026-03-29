from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from app.dependencies import get_broker
from app.schemas.order import OrderRequest, OrderOut, FillOut

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderOut, status_code=201)
async def place_order(req: OrderRequest, broker=Depends(get_broker)):
    return await broker.place_order(req)


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: Optional[str] = None,
    ticker: Optional[str] = None,
    limit: int = Query(50, le=200),
    broker=Depends(get_broker),
):
    return await broker.get_orders(status=status, ticker=ticker, limit=limit)


@router.get("/fills", response_model=list[FillOut])
async def list_fills(
    ticker: Optional[str] = None,
    limit: int = Query(50, le=200),
    broker=Depends(get_broker),
):
    return await broker.get_fills(ticker=ticker, limit=limit)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: str, broker=Depends(get_broker)):
    order = await broker.get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.delete("/{order_id}")
async def cancel_order(order_id: str, broker=Depends(get_broker)):
    success = await broker.cancel_order(order_id)
    return {"cancelled": success, "order_id": order_id}
