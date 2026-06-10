"""
Backtest API endpoints.
Backtest jobs run in the background. Use SSE to stream progress.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse

from app.dependencies import get_broker
from app.schemas.backtest import BacktestRequest, BacktestRunOut
from app.services.backtest_engine import BacktestEngine
from app.core.strategies import STRATEGY_REGISTRY

router = APIRouter(prefix="/backtest", tags=["backtest"])

# In-memory storage for backtest runs (replace with DB in production)
_runs: dict[str, dict] = {}


@router.post("/run", response_model=BacktestRunOut, status_code=202)
async def start_backtest(
    req: BacktestRequest,
    background_tasks: BackgroundTasks,
    broker=Depends(get_broker),
):
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    if req.strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(400, f"Unknown strategy: {req.strategy_name}. Available: {list(STRATEGY_REGISTRY)}")

    _runs[run_id] = {
        "id": run_id,
        "strategy_name": req.strategy_name,
        "params": req.params,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "status": "pending",
        "created_at": now,
        "completed_at": None,
        "result": None,
        "error": None,
        "progress": [],
    }

    background_tasks.add_task(_run_backtest, run_id, req, broker)

    return BacktestRunOut(
        id=run_id,
        strategy_name=req.strategy_name,
        start_date=req.start_date,
        end_date=req.end_date,
        status="pending",
        created_at=now,
    )


async def _run_backtest(run_id: str, req: BacktestRequest, broker) -> None:
    """Background task: run backtest and store results."""
    _runs[run_id]["status"] = "running"
    try:
        strategy_cls = STRATEGY_REGISTRY[req.strategy_name]
        strategy = strategy_cls(params=req.params)
        strategy.enabled = True

        # Fetch historical markets for the strategy to fit on
        try:
            markets = await broker.get_markets(status="active", limit=200)
        except Exception:
            markets = []

        markets_meta = {m.ticker: m for m in markets}

        def progress_cb(current: int, total: int, msg: str) -> None:
            _runs[run_id]["progress"].append({"step": current, "total": total, "message": msg})

        engine = BacktestEngine()
        result = await engine.run(
            strategy=strategy,
            snapshots=markets,  # In real impl: load from DB market_snapshots table
            markets_meta=markets_meta,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
            n_splits=req.n_splits,
            embargo_days=req.embargo_days,
            kelly_fraction=0.25,
            progress_callback=progress_cb,
        )

        agg = result.aggregate_metrics
        _runs[run_id].update({
            "status": "complete",
            "completed_at": datetime.now(timezone.utc),
            "total_return": agg.get("total_return"),
            "sharpe_ratio": agg.get("sharpe_ratio"),
            "sortino_ratio": agg.get("sortino_ratio"),
            "max_drawdown": agg.get("max_drawdown"),
            "win_rate": agg.get("win_rate"),
            "num_trades": agg.get("num_trades"),
            "profit_factor": agg.get("profit_factor"),
            "result": {
                "fold_results": [
                    {
                        "fold_idx": fr.fold_idx,
                        "train_start": fr.train_start.isoformat(),
                        "train_end": fr.train_end.isoformat(),
                        "test_start": fr.test_start.isoformat(),
                        "test_end": fr.test_end.isoformat(),
                        "metrics": fr.metrics,
                    }
                    for fr in result.fold_results
                ],
                "equity_curve": result.equity_curve,
                "trades": result.all_trades,
            },
        })
    except Exception as e:
        _runs[run_id]["status"] = "failed"
        _runs[run_id]["error"] = str(e)


@router.get("/runs", response_model=list[BacktestRunOut])
async def list_runs():
    runs = []
    for run_id, run in sorted(_runs.items(), key=lambda x: x[1]["created_at"], reverse=True):
        runs.append(BacktestRunOut(
            id=run["id"],
            strategy_name=run["strategy_name"],
            start_date=run["start_date"],
            end_date=run["end_date"],
            status=run["status"],
            total_return=run.get("total_return"),
            sharpe_ratio=run.get("sharpe_ratio"),
            sortino_ratio=run.get("sortino_ratio"),
            max_drawdown=run.get("max_drawdown"),
            win_rate=run.get("win_rate"),
            num_trades=run.get("num_trades"),
            profit_factor=run.get("profit_factor"),
            error_msg=run.get("error"),
            created_at=run["created_at"],
            completed_at=run.get("completed_at"),
        ))
    return runs


@router.get("/runs/{run_id}", response_model=BacktestRunOut)
async def get_run(run_id: str):
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return BacktestRunOut(
        id=run["id"],
        strategy_name=run["strategy_name"],
        start_date=run["start_date"],
        end_date=run["end_date"],
        status=run["status"],
        total_return=run.get("total_return"),
        sharpe_ratio=run.get("sharpe_ratio"),
        sortino_ratio=run.get("sortino_ratio"),
        max_drawdown=run.get("max_drawdown"),
        win_rate=run.get("win_rate"),
        num_trades=run.get("num_trades"),
        profit_factor=run.get("profit_factor"),
        error_msg=run.get("error"),
        created_at=run["created_at"],
        completed_at=run.get("completed_at"),
    )


@router.get("/runs/{run_id}/stream")
async def stream_progress(run_id: str):
    """SSE stream for backtest progress."""
    async def event_stream() -> AsyncGenerator[str, None]:
        last_idx = 0
        while True:
            run = _runs.get(run_id)
            if not run:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            progress = run.get("progress", [])
            while last_idx < len(progress):
                yield f"data: {json.dumps(progress[last_idx])}\n\n"
                last_idx += 1
            if run["status"] in ("complete", "failed"):
                yield f"data: {json.dumps({'status': run['status'], 'done': True})}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
