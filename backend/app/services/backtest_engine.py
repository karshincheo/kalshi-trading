"""
Backtesting Engine — Walk-forward cross-validation with purging and embargo.

Implements the Lopez de Prado methodology to prevent data leakage:
1. Walk-forward only (training always precedes testing)
2. Embargo gap between training and test folds
3. Purging: remove training observations with labels overlapping test period
4. Tick-by-tick replay: strategy sees ONLY data up to current timestamp

Anti-leakage guarantees:
- strategy.fit() is called ONLY on training data
- generate_signals() receives ONLY snapshots before current tick
- Strategy state is reset between folds
- No market that settles in the embargo window is used in training

References:
- López de Prado (2018). Advances in Financial Machine Learning.
- López de Prado (2020). Machine Learning for Asset Managers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional, AsyncIterator, Callable

from app.broker.paper_broker import PaperBroker
from app.core.math.kelly import kelly_full
from app.core.math.metrics import compute_all_metrics, equity_to_returns
from app.core.strategies.base import AbstractStrategy
from app.schemas.market import MarketOut
from app.schemas.order import OrderRequest

log = logging.getLogger(__name__)


@dataclass
class BacktestFold:
    fold_idx: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    train_snapshots: list[MarketOut]
    test_snapshots_by_tick: list[tuple[datetime, list[MarketOut]]]


@dataclass
class FoldResult:
    fold_idx: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    equity_curve: list[tuple[datetime, float]]
    trade_pnls: list[float]
    trades: list[dict]
    metrics: dict


@dataclass
class BacktestResult:
    run_id: str
    fold_results: list[FoldResult]
    aggregate_metrics: dict
    equity_curve: list[dict]  # [{timestamp, equity}]
    all_trades: list[dict]


class BacktestEngine:
    """
    Walk-forward backtesting engine.

    Usage:
        engine = BacktestEngine()
        result = await engine.run(
            strategy=LongshotBiasStrategy(),
            snapshots=historical_snapshots,
            markets_meta=markets_metadata,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=10_000,
            n_splits=5,
            embargo_days=5,
        )
    """

    async def run(
        self,
        strategy: AbstractStrategy,
        snapshots: list[MarketOut],         # Historical market snapshots, sorted by timestamp
        markets_meta: dict[str, MarketOut], # Current market metadata (for close_time lookup)
        start_date: date,
        end_date: date,
        initial_capital: float = 10_000.0,
        n_splits: int = 5,
        embargo_days: int = 5,
        kelly_fraction: float = 0.25,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> BacktestResult:
        """Run full walk-forward backtest."""
        run_id = str(uuid.uuid4())
        log.info("Starting backtest %s: %s splits, %s embargo days", run_id, n_splits, embargo_days)

        # 1. Generate folds
        folds = self._generate_folds(
            snapshots, markets_meta, start_date, end_date, n_splits, embargo_days
        )

        if not folds:
            raise ValueError("Insufficient data to generate backtest folds")

        # 2. Run each fold
        fold_results: list[FoldResult] = []
        for i, fold in enumerate(folds):
            if progress_callback:
                progress_callback(i, len(folds), f"Running fold {i+1}/{len(folds)}")

            result = await self._run_fold(
                strategy=strategy,
                fold=fold,
                initial_capital=initial_capital,
                kelly_fraction=kelly_fraction,
            )
            fold_results.append(result)
            log.info(
                "Fold %d complete: return=%.2f%%, sharpe=%.2f, trades=%d",
                i + 1,
                (result.metrics.get("total_return") or 0) * 100,
                result.metrics.get("sharpe_ratio") or 0,
                len(result.trade_pnls),
            )

        # 3. Aggregate results
        all_trades = []
        for fr in fold_results:
            all_trades.extend(fr.trades)

        combined_equity = []
        combined_pnls = []
        combined_equity_curve = []
        for fr in fold_results:
            for ts, eq in fr.equity_curve:
                combined_equity.append(eq)
                combined_equity_curve.append({"timestamp": ts.isoformat(), "equity": eq})
            combined_pnls.extend(fr.trade_pnls)

        agg_metrics = compute_all_metrics(combined_equity, combined_pnls)

        if progress_callback:
            progress_callback(len(folds), len(folds), "Complete")

        return BacktestResult(
            run_id=run_id,
            fold_results=fold_results,
            aggregate_metrics=agg_metrics,
            equity_curve=combined_equity_curve,
            all_trades=all_trades,
        )

    def _generate_folds(
        self,
        snapshots: list[MarketOut],
        markets_meta: dict[str, MarketOut],
        start_date: date,
        end_date: date,
        n_splits: int,
        embargo_days: int,
    ) -> list[BacktestFold]:
        """
        Generate walk-forward folds with purging and embargo.

        Timeline for expanding-window walk-forward:
          Fold 0: train=[start, t1], embargo=[t1, t1+embargo], test=[t1+embargo, t2]
          Fold 1: train=[start, t2], embargo=[t2, t2+embargo], test=[t2+embargo, t3]
          ...

        Purging: Any snapshot for a market whose close_time falls within
                 [fold_train_end, fold_test_start] is removed from training data.
        """
        total_days = (end_date - start_date).days
        if total_days < n_splits * (embargo_days + 5):
            log.warning("Date range too short for %d splits with %d embargo days", n_splits, embargo_days)
            n_splits = max(2, total_days // (embargo_days + 10))

        fold_size_days = total_days // (n_splits + 1)
        folds = []

        for i in range(n_splits):
            train_end = start_date + timedelta(days=fold_size_days * (i + 1))
            test_start = train_end + timedelta(days=embargo_days)
            test_end = start_date + timedelta(days=fold_size_days * (i + 2))
            test_end = min(test_end, end_date)

            if test_start >= test_end:
                break

            # Get training snapshots (up to train_end), with purging
            train_snaps = self._get_train_snapshots(
                snapshots, markets_meta, start_date, train_end, test_start
            )

            # Get test snapshots grouped by tick (simulating live trading)
            test_ticks = self._get_test_ticks(snapshots, test_start, test_end)

            folds.append(BacktestFold(
                fold_idx=i,
                train_start=start_date,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                train_snapshots=train_snaps,
                test_snapshots_by_tick=test_ticks,
            ))

        return folds

    def _get_train_snapshots(
        self,
        snapshots: list[MarketOut],
        markets_meta: dict[str, MarketOut],
        train_start: date,
        train_end: date,
        test_start: date,
    ) -> list[MarketOut]:
        """
        Get training snapshots with purging applied.

        PURGING RULE: Remove any snapshot for a market whose close_time
        falls within [train_end, test_start]. These markets' outcomes
        will become known in the embargo period — keeping them in training
        would leak label information.
        """
        contamination_start = train_end
        contamination_end = test_start

        result = []
        for snap in snapshots:
            # Filter by date range
            if not hasattr(snap, '_timestamp') or snap._timestamp is None:
                continue
            snap_date = snap._timestamp.date() if isinstance(snap._timestamp, datetime) else snap._timestamp
            if snap_date < train_start or snap_date >= train_end:
                continue

            # Purging check: is this market's close_time in contamination window?
            meta = markets_meta.get(snap.ticker)
            if meta and meta.close_time:
                close_date = meta.close_time.date()
                if contamination_start <= close_date <= contamination_end:
                    continue  # Purged: label would leak into test period

            result.append(snap)

        return result

    def _get_test_ticks(
        self,
        snapshots: list[MarketOut],
        test_start: date,
        test_end: date,
    ) -> list[tuple[datetime, list[MarketOut]]]:
        """
        Group test snapshots by timestamp.
        Each tick contains all markets visible at that exact moment.
        """
        from collections import defaultdict
        ticks: dict[datetime, list[MarketOut]] = defaultdict(list)

        for snap in snapshots:
            if not hasattr(snap, '_timestamp') or snap._timestamp is None:
                continue
            snap_date = snap._timestamp.date() if isinstance(snap._timestamp, datetime) else snap._timestamp
            if test_start <= snap_date < test_end:
                tick_ts = snap._timestamp if isinstance(snap._timestamp, datetime) else datetime.combine(
                    snap._timestamp, datetime.min.time(), tzinfo=timezone.utc
                )
                ticks[tick_ts].append(snap)

        return sorted(ticks.items())

    async def _run_fold(
        self,
        strategy: AbstractStrategy,
        fold: BacktestFold,
        initial_capital: float,
        kelly_fraction: float,
    ) -> FoldResult:
        """
        Run strategy on a single fold's test period.

        ANTI-LEAKAGE: Strategy only sees data up to current_tick timestamp.
        Strategy state and paper broker are reset at fold start.
        """
        # Reset strategy state
        strategy.reset()

        # Fit on training data ONLY
        if fold.train_snapshots:
            strategy.fit(fold.train_snapshots)

        # Fresh paper broker per fold
        broker = PaperBroker(initial_balance=initial_capital, slippage_bps=5.0)

        equity_curve: list[tuple[datetime, float]] = []
        trade_pnls: list[float] = []
        trades: list[dict] = []

        prev_equity = initial_capital

        # Tick through test period sequentially
        for tick_ts, tick_markets in fold.test_snapshots_by_tick:
            # Update broker market cache (what strategy can see right now)
            for market in tick_markets:
                broker.update_market(market)

            # Trigger fill of any queued limit orders at current prices
            broker.tick()

            # Generate signals (strategy sees ONLY current and past data)
            portfolio = await broker.get_portfolio_summary()
            equity = portfolio.total_equity

            try:
                signals = strategy.generate_signals(tick_markets, equity)
            except Exception as e:
                log.debug("Backtest strategy error at %s: %s", tick_ts, e)
                signals = []

            # Execute signals
            for signal in signals:
                kelly_res = kelly_full(
                    p_true=signal.fair_value,
                    market_price=signal.market_price,
                    bankroll=equity,
                    fraction=kelly_fraction,
                    min_edge=0.02,
                    max_position_pct=0.05,
                )

                if kelly_res.recommended_contracts <= 0:
                    continue

                req = OrderRequest(
                    ticker=signal.ticker,
                    action=signal.direction,
                    order_type="market",
                    count=kelly_res.recommended_contracts,
                    strategy_name=signal.strategy_name,
                )
                try:
                    order = await broker.place_order(req)
                    if order.filled_count > 0:
                        fill_cost = order.avg_fill_price * order.filled_count if order.avg_fill_price else 0
                        trades.append({
                            "fold_idx": fold.fold_idx,
                            "ticker": signal.ticker,
                            "action": signal.direction,
                            "count": order.filled_count,
                            "entry_price": order.avg_fill_price or signal.market_price,
                            "entry_time": tick_ts.isoformat(),
                            "strategy_name": signal.strategy_name,
                        })
                except Exception as e:
                    log.debug("Backtest order error: %s", e)

            # Track equity
            portfolio = await broker.get_portfolio_summary()
            equity_curve.append((tick_ts, portfolio.total_equity))

            if portfolio.total_equity != prev_equity:
                trade_pnls.append(portfolio.total_equity - prev_equity)
            prev_equity = portfolio.total_equity

        # Compute fold metrics
        equities = [e for _, e in equity_curve]
        metrics = compute_all_metrics(equities, trade_pnls)
        metrics["fold_idx"] = fold.fold_idx

        return FoldResult(
            fold_idx=fold.fold_idx,
            train_start=fold.train_start,
            train_end=fold.train_end,
            test_start=fold.test_start,
            test_end=fold.test_end,
            equity_curve=equity_curve,
            trade_pnls=trade_pnls,
            trades=trades,
            metrics=metrics,
        )
