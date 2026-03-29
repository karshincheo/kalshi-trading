from fastapi import APIRouter, Depends, Query
from typing import Optional
from app.dependencies import get_scanner_service
from app.schemas.strategy import OpportunityOut

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.get("/opportunities", response_model=list[OpportunityOut])
async def get_opportunities(
    strategy: Optional[str] = None,
    min_edge_score: float = Query(0.0, ge=0, le=100),
    limit: int = Query(50, le=200),
    scanner_service=Depends(get_scanner_service),
):
    if scanner_service is None:
        return []
    strategy_filter = [strategy] if strategy else None
    return await scanner_service.get_opportunities(
        strategy_filter=strategy_filter,
        min_edge_score=min_edge_score,
        limit=limit,
    )
