"""
Module B: Backtesting Engine.

Executes LLM-generated strategy code against historical data via the sandbox,
simulates trading through PaperBroker, and computes performance metrics.

This module is immutable — the agent cannot modify it.
"""
from __future__ import annotations

import logging


from app.autoresearch.config import AutoresearchSettings
from app.autoresearch.prepare import AGENT_COLUMNS
from app.autoresearch.sandbox import execute_strategy, validate_strategy_source
from app.autoresearch.scoring import EvaluationResult
from app.core.math.kelly import kelly_full, kelly_for_no
from app.core.math.metrics import (
    brier_score,
    compute_all_metrics,
)

logger = logging.getLogger(__name__)


class Evaluator:
    """Evaluates a strategy against a dataset, returning full metrics."""

    def __init__(self, config: AutoresearchSettings) -> None:
        self.config = config

    def evaluate(
        self,
        strategy_code: str,
        df,  # pd.DataFrame with both agent + label columns
        label: str = "val",
    ) -> EvaluationResult:
        """
        Run a strategy through the sandbox and score it.

        Args:
            strategy_code: Python source with predict(row) function.
            df: DataFrame with agent columns + outcome labels.
            label: Label for logging ("train" or "val").

        Returns:
            EvaluationResult with all metrics.
        """
        import pandas as pd

        # Validate source first
        errors = validate_strategy_source(strategy_code)
        if errors:
            return self._error_result(
                f"Validation failed: {'; '.join(errors)}"
            )

        # Prepare agent-visible rows (no labels)
        agent_cols = [c for c in AGENT_COLUMNS if c in df.columns]
        agent_df = df[agent_cols].copy()
        rows = agent_df.to_dict(orient="records")

        if not rows:
            return self._error_result("No data rows to evaluate.")

        # Execute in sandbox
        predictions, error_log, elapsed = execute_strategy(
            strategy_code,
            rows,
            timeout_seconds=self.config.sandbox_timeout_seconds,
            sandbox_dir=self.config.sandbox_dir,
        )

        if not predictions:
            return EvaluationResult(
                brier_score=1.0,
                sharpe_ratio=None,
                sortino_ratio=None,
                max_drawdown=0.0,
                win_rate=0.0,
                profit_factor=None,
                total_return=0.0,
                num_trades=0,
                elapsed_seconds=elapsed,
                error_log=error_log or "No predictions returned.",
                predictions=[],
                equity_curve=[self.config.initial_capital],
                timed_out="TIMEOUT" in (error_log or ""),
            )

        # Simulate trading
        equity_curve, trade_pnls = self._simulate_trades(predictions, df)

        # Compute Brier score (only for rows where outcome is known)
        pred_probs = []
        outcomes = []
        for i, pred in enumerate(predictions):
            if i < len(df):
                outcome = df.iloc[i].get("outcome")
                if pd.notna(outcome):
                    fair_value = pred.get("fair_value", 0.5)
                    pred_probs.append(float(fair_value))
                    outcomes.append(int(outcome))

        bs = brier_score(pred_probs, outcomes) if pred_probs else 1.0

        # Compute trading metrics
        metrics = compute_all_metrics(equity_curve, trade_pnls)

        n_trades = len(trade_pnls)
        n_actions = sum(
            1 for p in predictions if p.get("action", "PASS") != "PASS"
        )

        logger.info(
            "[%s] Brier=%.4f Sharpe=%s Trades=%d Actions=%d Time=%.1fs",
            label,
            bs,
            f"{metrics['sharpe_ratio']:.2f}" if metrics["sharpe_ratio"] else "N/A",
            n_trades,
            n_actions,
            elapsed,
        )

        return EvaluationResult(
            brier_score=bs,
            sharpe_ratio=metrics["sharpe_ratio"],
            sortino_ratio=metrics["sortino_ratio"],
            max_drawdown=metrics["max_drawdown"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            total_return=metrics["total_return"],
            num_trades=n_trades,
            elapsed_seconds=elapsed,
            error_log=error_log or "",
            predictions=predictions,
            equity_curve=equity_curve,
            timed_out=False,
        )

    def _simulate_trades(
        self,
        predictions: list[dict],
        df,  # pd.DataFrame
    ) -> tuple[list[float], list[float]]:
        """
        Simulate trades through a lightweight portfolio tracker.

        Returns (equity_curve, trade_pnls).
        """
        import pandas as pd

        capital = self.config.initial_capital
        cash = capital
        positions = {}  # ticker -> {side, count, avg_cost}
        equity_curve = [capital]
        trade_pnls = []

        for i, pred in enumerate(predictions):
            action = pred.get("action", "PASS").upper()
            if action == "PASS" or i >= len(df):
                equity_curve.append(cash + self._position_value(positions, df, i))
                continue

            row = df.iloc[i]
            ticker = row.get("market_ticker", f"row_{i}")
            fair_value = float(pred.get("fair_value", 0.5))
            yes_mid = float(row.get("yes_mid", 0.5) or 0.5)

            # Size via Kelly
            if action == "BUY_YES":
                kelly = kelly_full(
                    p_true=fair_value,
                    market_price=yes_mid,
                    bankroll=cash,
                    fraction=self.config.kelly_fraction,
                    min_edge=0.02,
                    max_position_pct=0.10,
                )
                contracts = kelly.recommended_contracts
                if contracts > 0:
                    fill_price = yes_mid + self.config.slippage_bps / 10000
                    fill_price = min(fill_price, 0.99)
                    cost = contracts * fill_price
                    fee = cost * self.config.kalshi_fee_bps / 10000
                    if cost + fee <= cash:
                        cash -= cost + fee
                        positions[ticker] = {
                            "side": "yes",
                            "count": contracts,
                            "avg_cost": fill_price,
                        }

            elif action == "BUY_NO":
                no_price = 1.0 - yes_mid
                kelly = kelly_for_no(
                    p_true_yes=fair_value,
                    no_market_price=no_price,
                    bankroll=cash,
                    fraction=self.config.kelly_fraction,
                    min_edge=0.02,
                    max_position_pct=0.10,
                )
                contracts = kelly.recommended_contracts
                if contracts > 0:
                    fill_price = no_price + self.config.slippage_bps / 10000
                    fill_price = min(fill_price, 0.99)
                    cost = contracts * fill_price
                    fee = cost * self.config.kalshi_fee_bps / 10000
                    if cost + fee <= cash:
                        cash -= cost + fee
                        positions[ticker] = {
                            "side": "no",
                            "count": contracts,
                            "avg_cost": fill_price,
                        }

            equity_curve.append(cash + self._position_value(positions, df, i))

        # Settle all remaining positions at outcome
        for ticker, pos in list(positions.items()):
            # Find the last row for this ticker to get outcome
            ticker_rows = df[df["market_ticker"] == ticker]
            if ticker_rows.empty:
                continue
            outcome = ticker_rows.iloc[-1].get("outcome")
            if pd.isna(outcome):
                continue

            count = pos["count"]
            avg_cost = pos["avg_cost"]

            if pos["side"] == "yes":
                payout = count * 1.0 if outcome == 1 else 0.0
            else:
                payout = count * 1.0 if outcome == 0 else 0.0

            pnl = payout - count * avg_cost
            trade_pnls.append(pnl)
            cash += payout

        equity_curve.append(cash)
        return equity_curve, trade_pnls

    @staticmethod
    def _position_value(positions: dict, df, current_idx: int) -> float:
        """Estimate current position value using latest mid prices."""

        value = 0.0
        for ticker, pos in positions.items():
            # Use current market mid as estimate
            ticker_rows = df[df["market_ticker"] == ticker]
            if ticker_rows.empty:
                continue
            # Find the closest row at or before current_idx
            valid = ticker_rows[ticker_rows.index <= current_idx]
            if valid.empty:
                continue
            mid = valid.iloc[-1].get("yes_mid", 0.5) or 0.5
            count = pos["count"]
            if pos["side"] == "yes":
                value += count * mid
            else:
                value += count * (1.0 - mid)
        return value

    def _error_result(self, msg: str) -> EvaluationResult:
        return EvaluationResult(
            brier_score=1.0,
            sharpe_ratio=None,
            sortino_ratio=None,
            max_drawdown=0.0,
            win_rate=0.0,
            profit_factor=None,
            total_return=0.0,
            num_trades=0,
            elapsed_seconds=0.0,
            error_log=msg,
            predictions=[],
            equity_curve=[self.config.initial_capital],
            timed_out=False,
        )
