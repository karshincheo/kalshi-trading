"""
Module D: The Orchestrator.

Manages the LLM-driven research loop:
  1. Load data → 2. Evaluate current strategy → 3. Prompt LLM →
  4. Extract code → 5. Validate → 6. Evaluate new → 7. Accept/reject →
  8. Commit → repeat

Stops when: max iterations, target Brier achieved, plateau detected, or SIGINT.
"""
from __future__ import annotations

import json
import logging
import re
import signal
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic

from app.autoresearch.config import AutoresearchSettings
from app.autoresearch.evaluate import Evaluator
from app.autoresearch.git_manager import GitManager
from app.autoresearch.prepare import DataPipeline
from app.autoresearch.sandbox import validate_strategy_source
from app.autoresearch.scoring import EvaluationResult

logger = logging.getLogger(__name__)


@dataclass
class IterationRecord:
    """Summary of one iteration for the history ring buffer."""
    iteration: int
    hypothesis: str
    val_brier: float
    val_sharpe: Optional[float]
    accepted: bool
    error: str = ""


@dataclass
class OrchestratorResult:
    """Final result of the autoresearch loop."""
    run_id: str
    total_iterations: int
    best_brier: float
    best_sharpe: Optional[float]
    best_iteration: int
    best_code: str
    stop_reason: str


class Orchestrator:
    """Drives the autonomous research loop."""

    def __init__(
        self,
        config: AutoresearchSettings,
        pipeline: DataPipeline,
        evaluator: Evaluator,
        git_manager: GitManager,
    ) -> None:
        self.config = config
        self.pipeline = pipeline
        self.evaluator = evaluator
        self.git = git_manager
        self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._stop_requested = False
        self._prompt_template = self._load_prompt_template()

    def run(
        self,
        max_iterations: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        resume_code: Optional[str] = None,
    ) -> OrchestratorResult:
        """
        Execute the full autoresearch loop.

        Args:
            max_iterations: Override config max_iterations.
            start_date: Data start date.
            end_date: Data end date.
            resume_code: Strategy code to resume from (instead of seed).

        Returns:
            OrchestratorResult with the best strategy found.
        """
        max_iter = max_iterations or self.config.max_iterations
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

        # Register SIGINT handler
        original_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_sigint)

        try:
            return self._run_loop(run_id, max_iter, start_date, end_date, resume_code)
        finally:
            signal.signal(signal.SIGINT, original_handler)
            self.pipeline.close()

    def _run_loop(
        self,
        run_id: str,
        max_iter: int,
        start_date: Optional[date],
        end_date: Optional[date],
        resume_code: Optional[str],
    ) -> OrchestratorResult:
        # Step 1: Load and split data
        logger.info("Building dataset...")
        df = self.pipeline.build_dataset(start_date, end_date)
        if df.empty:
            return OrchestratorResult(
                run_id=run_id, total_iterations=0,
                best_brier=1.0, best_sharpe=None,
                best_iteration=0, best_code="",
                stop_reason="No data available.",
            )

        train, val, holdout = self.pipeline.split(df)
        logger.info("Data splits: train=%d, val=%d, holdout=%d", len(train), len(val), len(holdout))

        if val.empty:
            return OrchestratorResult(
                run_id=run_id, total_iterations=0,
                best_brier=1.0, best_sharpe=None,
                best_iteration=0, best_code="",
                stop_reason="Insufficient data for validation split.",
            )

        # Step 2: Initialize git
        self.git.init_repo()
        branch = self.git.create_branch(run_id)

        # Step 3: Load starting strategy
        if resume_code:
            current_code = resume_code
        else:
            seed_path = Path(__file__).parent / "strategies" / "seed_strategy.py"
            current_code = seed_path.read_text()

        # Step 4: Main loop
        best_brier = float("inf")
        best_sharpe = None
        best_code = current_code
        best_iteration = 0
        plateau_counter = 0
        history: deque[IterationRecord] = deque(maxlen=10)

        logger.info("Starting autoresearch loop: run_id=%s, max_iter=%d", run_id, max_iter)

        for iteration in range(1, max_iter + 1):
            if self._stop_requested:
                return self._make_result(
                    run_id, iteration - 1, best_brier, best_sharpe,
                    best_iteration, best_code, "User interrupted (SIGINT).",
                )

            t0 = time.monotonic()
            logger.info("=== Iteration %d/%d ===", iteration, max_iter)

            # Evaluate current strategy on train + val
            train_result = self.evaluator.evaluate(current_code, train, label="train")
            val_result = self.evaluator.evaluate(current_code, val, label="val")

            # Build LLM prompt
            prompt = self._build_prompt(
                current_code, train_result, val_result, history, best_brier,
            )

            # Call LLM
            new_code = self._call_llm_with_retries(prompt, iteration)
            if new_code is None:
                record = IterationRecord(
                    iteration=iteration, hypothesis="LLM failed to produce code",
                    val_brier=val_result.brier_score, val_sharpe=val_result.sharpe_ratio,
                    accepted=False, error="LLM code extraction failed",
                )
                history.append(record)
                plateau_counter += 1
                if plateau_counter >= self.config.plateau_patience:
                    return self._make_result(
                        run_id, iteration, best_brier, best_sharpe,
                        best_iteration, best_code, f"Plateau: {plateau_counter} iterations without improvement.",
                    )
                continue

            # Evaluate new strategy on validation
            new_val_result = self.evaluator.evaluate(new_code, val, label="val-new")

            # Extract hypothesis from code comment
            hypothesis = self._extract_hypothesis(new_code)

            # Accept or reject
            accepted = (
                new_val_result.passed
                and new_val_result.brier_score < best_brier
            )

            if accepted:
                best_brier = new_val_result.brier_score
                best_sharpe = new_val_result.sharpe_ratio
                best_code = new_code
                best_iteration = iteration
                current_code = new_code
                plateau_counter = 0
                logger.info(
                    "ACCEPTED iter %d: brier=%.4f sharpe=%s",
                    iteration, best_brier,
                    f"{best_sharpe:.2f}" if best_sharpe else "N/A",
                )
            else:
                plateau_counter += 1
                logger.info(
                    "rejected iter %d: brier=%.4f (best=%.4f)",
                    iteration, new_val_result.brier_score, best_brier,
                )

            # Commit to git
            commit_hash = self.git.commit_iteration(
                iteration=iteration,
                strategy_code=new_code,
                val_brier=new_val_result.brier_score,
                val_sharpe=new_val_result.sharpe_ratio,
                hypothesis=hypothesis,
                accepted=accepted,
            )

            # Record
            record = IterationRecord(
                iteration=iteration,
                hypothesis=hypothesis,
                val_brier=new_val_result.brier_score,
                val_sharpe=new_val_result.sharpe_ratio,
                accepted=accepted,
                error=new_val_result.error_log[:200] if new_val_result.error_log else "",
            )
            history.append(record)

            elapsed = time.monotonic() - t0
            logger.info("Iteration %d completed in %.1fs", iteration, elapsed)

            # Check stop conditions
            if best_brier <= self.config.target_brier:
                return self._make_result(
                    run_id, iteration, best_brier, best_sharpe,
                    best_iteration, best_code, f"Target Brier {self.config.target_brier} achieved.",
                )

            if plateau_counter >= self.config.plateau_patience:
                return self._make_result(
                    run_id, iteration, best_brier, best_sharpe,
                    best_iteration, best_code, f"Plateau: {plateau_counter} iterations without improvement.",
                )

        return self._make_result(
            run_id, max_iter, best_brier, best_sharpe,
            best_iteration, best_code, "Max iterations reached.",
        )

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    def _call_llm_with_retries(self, prompt: str, iteration: int) -> Optional[str]:
        """Call LLM, extract code, validate. Retry up to max_retries on errors."""
        last_error = ""

        for attempt in range(1, self.config.sandbox_max_retries + 1):
            # If retrying, append the error to the prompt
            retry_prompt = prompt
            if last_error:
                retry_prompt += (
                    f"\n\n## RETRY (attempt {attempt}/{self.config.sandbox_max_retries})\n"
                    f"Your previous code had this error:\n```\n{last_error}\n```\n"
                    f"Please fix the issue and return the complete strategy.py."
                )

            response = self._call_llm(retry_prompt)
            if not response:
                last_error = "LLM returned empty response"
                continue

            code = self._extract_code(response)
            if not code:
                last_error = "No ```python code block found in response"
                continue

            errors = validate_strategy_source(code)
            if errors:
                last_error = "; ".join(errors)
                logger.warning("Iter %d attempt %d validation: %s", iteration, attempt, last_error)
                continue

            return code

        logger.error("Iter %d: all %d attempts failed. Last error: %s", iteration, self.config.sandbox_max_retries, last_error)
        return None

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call the Anthropic API."""
        try:
            response = self._client.messages.create(
                model=self.config.anthropic_model,
                max_tokens=self.config.llm_max_tokens,
                temperature=self.config.llm_temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text if response.content else None
        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            return None
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        current_code: str,
        train_result: EvaluationResult,
        val_result: EvaluationResult,
        history: deque,
        best_brier: float,
    ) -> str:
        """Fill in the prompt template with current metrics."""
        history_text = ""
        if history:
            lines = []
            for rec in history:
                status = "ACCEPTED" if rec.accepted else "rejected"
                sharpe_str = f"{rec.val_sharpe:.2f}" if rec.val_sharpe else "N/A"
                lines.append(
                    f"  iter {rec.iteration} [{status}]: brier={rec.val_brier:.4f} "
                    f"sharpe={sharpe_str} — {rec.hypothesis[:80]}"
                )
                if rec.error:
                    lines.append(f"    error: {rec.error[:100]}")
            history_text = "\n".join(lines)
        else:
            history_text = "  (first iteration — no history yet)"

        def _fmt(v, fmt=".4f"):
            return f"{v:{fmt}}" if v is not None else "N/A"

        return self._prompt_template.format(
            best_brier=_fmt(best_brier if best_brier < float("inf") else None),
            current_sharpe=_fmt(val_result.sharpe_ratio, ".2f"),
            iteration_history=history_text,
            current_strategy_code=current_code,
            train_brier=_fmt(train_result.brier_score),
            val_brier=_fmt(val_result.brier_score),
            train_sharpe=_fmt(train_result.sharpe_ratio, ".2f"),
            val_sharpe=_fmt(val_result.sharpe_ratio, ".2f"),
            train_trades=str(train_result.num_trades),
            val_trades=str(val_result.num_trades),
            train_winrate=_fmt(train_result.win_rate, ".1%"),
            val_winrate=_fmt(val_result.win_rate, ".1%"),
            execution_log=val_result.error_log[:500] if val_result.error_log else "(clean run)",
        )

    def _load_prompt_template(self) -> str:
        """Load program.md prompt template."""
        prompt_path = Path(__file__).parent / "program.md"
        return prompt_path.read_text()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_code(response: str) -> Optional[str]:
        """Extract Python code from ```python ... ``` markers."""
        pattern = r"```python\s*\n(.*?)```"
        matches = re.findall(pattern, response, re.DOTALL)
        if not matches:
            # Try without language specifier
            pattern = r"```\s*\n(.*?)```"
            matches = re.findall(pattern, response, re.DOTALL)
        if matches:
            # Return the longest match (most likely the full strategy)
            return max(matches, key=len).strip()
        return None

    @staticmethod
    def _extract_hypothesis(code: str) -> str:
        """Extract the hypothesis comment from the top of strategy code."""
        lines = code.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") and len(stripped) > 5:
                # Skip shebang and encoding lines
                if stripped.startswith("#!") or "coding" in stripped:
                    continue
                return stripped.lstrip("# ").strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                # First line of docstring
                content = stripped.strip('"').strip("'").strip()
                if content:
                    return content
                # Multi-line docstring: get second line
                if len(lines) > lines.index(line) + 1:
                    return lines[lines.index(line) + 1].strip().strip('"').strip("'").strip()
        return "(no hypothesis stated)"

    def _handle_sigint(self, signum, frame):
        logger.info("SIGINT received — stopping after current iteration.")
        self._stop_requested = True

    @staticmethod
    def _make_result(
        run_id: str,
        total_iterations: int,
        best_brier: float,
        best_sharpe: Optional[float],
        best_iteration: int,
        best_code: str,
        stop_reason: str,
    ) -> OrchestratorResult:
        logger.info(
            "Run %s complete: %d iterations, best_brier=%.4f, reason=%s",
            run_id, total_iterations, best_brier, stop_reason,
        )
        return OrchestratorResult(
            run_id=run_id,
            total_iterations=total_iterations,
            best_brier=best_brier,
            best_sharpe=best_sharpe,
            best_iteration=best_iteration,
            best_code=best_code,
            stop_reason=stop_reason,
        )
