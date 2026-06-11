"""
CLI entry point for the Autonomous Climate Quant Researcher.

Usage:
    python -m app.autoresearch.cli collect [--once]
    python -m app.autoresearch.cli run [--iterations N] [--model MODEL] [--start-date DATE] [--end-date DATE]
    python -m app.autoresearch.cli evaluate [--strategy-file PATH]
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("autoresearch")


def cmd_collect(args: argparse.Namespace) -> None:
    """Run the data collector."""
    from app.autoresearch.config import AutoresearchSettings
    from app.autoresearch.collector import TemperatureMarketCollector

    config = AutoresearchSettings()
    collector = TemperatureMarketCollector(config)

    if args.once:
        n = collector.collect_once()
        n_settled = collector.collect_settlements()
        print(f"Collected {n} snapshots, {n_settled} settlements.")
        collector.close()
    else:
        print(f"Starting continuous collection every {config.collector_interval_seconds}s...")
        print("Press Ctrl+C to stop.")
        collector.run_continuous()


def cmd_run(args: argparse.Namespace) -> None:
    """Run the autoresearch optimization loop."""
    from app.autoresearch.config import AutoresearchSettings
    from app.autoresearch.evaluate import Evaluator
    from app.autoresearch.git_manager import GitManager
    from app.autoresearch.loop import Orchestrator
    from app.autoresearch.prepare import DataPipeline

    config = AutoresearchSettings()

    # Override model if specified
    if args.model:
        config.anthropic_model = args.model

    if not config.anthropic_api_key:
        print("ERROR: AUTORESEARCH_ANTHROPIC_API_KEY environment variable is required.")
        print("Set it in your .env or shell: export AUTORESEARCH_ANTHROPIC_API_KEY=sk-...")
        sys.exit(1)

    pipeline = DataPipeline(config)
    evaluator = Evaluator(config)
    git_mgr = GitManager(config.iterations_dir)

    # Resume from file if specified
    resume_code = None
    if args.resume_from:
        resume_path = Path(args.resume_from)
        if resume_path.exists():
            resume_code = resume_path.read_text()
            print(f"Resuming from: {resume_path}")
        else:
            print(f"ERROR: Resume file not found: {resume_path}")
            sys.exit(1)

    # Parse dates
    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    end_date = date.fromisoformat(args.end_date) if args.end_date else None

    orchestrator = Orchestrator(config, pipeline, evaluator, git_mgr)

    print(f"Model: {config.anthropic_model}")
    print(f"Max iterations: {args.iterations}")
    print(f"Date range: {start_date or 'all'} to {end_date or 'all'}")
    print("Starting autoresearch loop... (Ctrl+C to stop gracefully)")
    print()

    result = orchestrator.run(
        max_iterations=args.iterations,
        start_date=start_date,
        end_date=end_date,
        resume_code=resume_code,
    )

    print()
    print("=" * 60)
    print(f"Run ID:           {result.run_id}")
    print(f"Iterations:       {result.total_iterations}")
    print(f"Best Brier Score: {result.best_brier:.4f}")
    print(f"Best Sharpe:      {result.best_sharpe:.2f}" if result.best_sharpe else "Best Sharpe:      N/A")
    print(f"Best Iteration:   {result.best_iteration}")
    print(f"Stop Reason:      {result.stop_reason}")
    print("=" * 60)

    # Save best strategy
    if result.best_code:
        out_path = config.iterations_dir / "best_strategy.py"
        out_path.write_text(result.best_code)
        print(f"\nBest strategy saved to: {out_path}")


def cmd_evaluate(args: argparse.Namespace) -> None:
    """Evaluate a specific strategy on the holdout set."""
    from app.autoresearch.config import AutoresearchSettings
    from app.autoresearch.evaluate import Evaluator
    from app.autoresearch.prepare import DataPipeline

    config = AutoresearchSettings()
    pipeline = DataPipeline(config)
    evaluator = Evaluator(config)

    # Load strategy
    strategy_path = Path(args.strategy_file)
    if not strategy_path.exists():
        print(f"ERROR: Strategy file not found: {strategy_path}")
        sys.exit(1)

    strategy_code = strategy_path.read_text()
    print(f"Evaluating: {strategy_path}")

    # Build dataset and get holdout
    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    end_date = date.fromisoformat(args.end_date) if args.end_date else None

    if args.dataset:
        import pandas as pd

        df = pd.read_parquet(args.dataset)
        df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    else:
        df = pipeline.build_dataset(start_date, end_date)
    if df.empty:
        print("ERROR: No data available.")
        sys.exit(1)

    if args.dataset:
        # Prebuilt sample: evaluate on the full frame (demo of the evaluator,
        # not an out-of-sample research result).
        holdout = df
        label = "sample"
    else:
        _, _, holdout = pipeline.split(df)
        label = "holdout"
    if holdout.empty:
        print("ERROR: Holdout set is empty.")
        sys.exit(1)

    print(f"{label.capitalize()} set: {len(holdout)} rows")

    # Market-implied baseline: how calibrated is the market price itself?
    baseline_brier = None
    if "implied_prob" in holdout.columns and "outcome" in holdout.columns:
        scored = holdout.dropna(subset=["implied_prob", "outcome"])
        if not scored.empty:
            baseline_brier = float(
                ((scored["implied_prob"] - scored["outcome"]) ** 2).mean()
            )

    result = evaluator.evaluate(strategy_code, holdout, label=label)

    print()
    print("=" * 40)
    if baseline_brier is not None:
        print(f"Brier Score:  {result.brier_score:.4f}  (market-implied baseline: {baseline_brier:.4f} — lower is better)")
    else:
        print(f"Brier Score:  {result.brier_score:.4f}")
    print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}" if result.sharpe_ratio else "Sharpe Ratio: N/A")
    print(f"Max Drawdown: {result.max_drawdown:.2%}")
    print(f"Win Rate:     {result.win_rate:.1%}")
    print(f"Trades:       {result.num_trades}")
    print(f"Total Return: {result.total_return:.2%}" if result.total_return else "Total Return: N/A")
    print(f"Time:         {result.elapsed_seconds:.1f}s")
    if result.error_log:
        print(f"Errors:       {result.error_log[:200]}")
    print("=" * 40)

    if result.sharpe_ratio and result.sharpe_ratio > 1.5 and result.brier_score < 0.20:
        print("\n*** STRATEGY PASSES HOLDOUT VALIDATION ***")
    else:
        print("\nStrategy does not meet holdout thresholds (Sharpe > 1.5, Brier < 0.20).")

    pipeline.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous Climate Quant Researcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # collect
    collect_parser = subparsers.add_parser("collect", help="Collect Kalshi temperature market data")
    collect_parser.add_argument("--once", action="store_true", help="Run one collection cycle and exit")

    # run
    run_parser = subparsers.add_parser("run", help="Run the autoresearch optimization loop")
    run_parser.add_argument("--iterations", type=int, default=1000, help="Max iterations")
    run_parser.add_argument("--model", type=str, default=None, help="LLM model override")
    run_parser.add_argument("--start-date", type=str, default=None, help="Data start date (YYYY-MM-DD)")
    run_parser.add_argument("--end-date", type=str, default=None, help="Data end date (YYYY-MM-DD)")
    run_parser.add_argument("--resume-from", type=str, default=None, help="Path to strategy file to resume from")

    # evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate a strategy on holdout data")
    eval_parser.add_argument("strategy_file", type=str, help="Path to strategy.py")
    eval_parser.add_argument("--start-date", type=str, default=None, help="Data start date (YYYY-MM-DD)")
    eval_parser.add_argument("--end-date", type=str, default=None, help="Data end date (YYYY-MM-DD)")
    eval_parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Path to a prebuilt dataset parquet (skips the cache rebuild; see data/autoresearch/sample/)",
    )

    args = parser.parse_args()

    if args.command == "collect":
        cmd_collect(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
