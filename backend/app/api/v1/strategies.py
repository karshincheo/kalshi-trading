import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_trading_engine, get_scanner_service
from app.schemas.strategy import StrategyOut, StrategyUpdate, SignalOut

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyOut])
async def list_strategies(engine=Depends(get_trading_engine)):
    if engine is None:
        return []
    result = []
    for i, strategy in enumerate(engine._strategies):
        result.append(StrategyOut(
            id=i,
            name=strategy.name,
            display_name=strategy.display_name,
            description=getattr(strategy, 'description', None),
            enabled=strategy.enabled,
            params=strategy.get_params(),
            capital_pct=0.1,
            updated_at=datetime.now(timezone.utc),
        ))
    return result


@router.get("/{name}", response_model=StrategyOut)
async def get_strategy(name: str, engine=Depends(get_trading_engine)):
    if engine is None:
        raise HTTPException(404, "Trading engine not initialized")
    for i, s in enumerate(engine._strategies):
        if s.name == name:
            return StrategyOut(
                id=i, name=s.name, display_name=s.display_name,
                description=getattr(s, 'description', None),
                enabled=s.enabled, params=s.get_params(),
                capital_pct=0.1, updated_at=datetime.now(timezone.utc),
            )
    raise HTTPException(404, f"Strategy '{name}' not found")


@router.put("/{name}", response_model=StrategyOut)
async def update_strategy(name: str, update: StrategyUpdate, engine=Depends(get_trading_engine)):
    if engine is None:
        raise HTTPException(404, "Trading engine not initialized")
    for i, s in enumerate(engine._strategies):
        if s.name == name:
            if update.enabled is not None:
                s.enabled = update.enabled
            if update.params is not None:
                s.set_params(update.params)
            return StrategyOut(
                id=i, name=s.name, display_name=s.display_name,
                description=getattr(s, 'description', None),
                enabled=s.enabled, params=s.get_params(),
                capital_pct=update.capital_pct or 0.1,
                updated_at=datetime.now(timezone.utc),
            )
    raise HTTPException(404, f"Strategy '{name}' not found")


@router.get("/{name}/signals", response_model=list[SignalOut])
async def get_recent_signals(name: str, engine=Depends(get_trading_engine)):
    if engine is None:
        return []
    signals = engine.get_recent_signals()
    return [
        SignalOut(
            ticker=s.ticker,
            direction=s.direction,
            fair_value=s.fair_value,
            market_price=s.market_price,
            edge=s.edge,
            confidence=s.confidence,
            suggested_size=0,
            kelly_fraction=0.0,
            strategy_name=s.strategy_name,
            metadata=s.metadata,
            generated_at=s.generated_at,
        )
        for s in signals if s.strategy_name == name
    ]
