from fastapi import APIRouter, Depends
from app.dependencies import get_broker
from app.schemas.position import PositionOut

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", response_model=list[PositionOut])
async def list_positions(broker=Depends(get_broker)):
    return await broker.get_positions()
