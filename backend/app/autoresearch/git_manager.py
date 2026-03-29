"""
Strategy version control via a dedicated git repository.

Each autoresearch run creates a branch. Each iteration commits the strategy
code with metrics in the commit message and a tag for the Brier score.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GitManager:
    """Manages a separate git repo for strategy iteration history."""

    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = Path(repo_dir)
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self._strategy_path = self.repo_dir / "strategy.py"

    def init_repo(self) -> None:
        """Initialize the git repo if it doesn't exist."""
        git_dir = self.repo_dir / ".git"
        if git_dir.exists():
            return
        self._run(["git", "init"])
        # Initial commit so branches work
        self._strategy_path.write_text("# Autoresearch strategy placeholder\n")
        self._run(["git", "add", "strategy.py"])
        self._run(["git", "commit", "-m", "init: autoresearch repo"])
        logger.info("Initialized autoresearch git repo at %s", self.repo_dir)

    def create_branch(self, run_id: str) -> str:
        """Create and checkout a branch for this run."""
        branch = f"run/{run_id}"
        self._run(["git", "checkout", "-b", branch])
        logger.info("Created branch: %s", branch)
        return branch

    def commit_iteration(
        self,
        iteration: int,
        strategy_code: str,
        val_brier: float,
        val_sharpe: Optional[float],
        hypothesis: str,
        accepted: bool,
    ) -> str:
        """
        Write strategy.py, commit, and tag if accepted.

        Returns the commit hash.
        """
        self._strategy_path.write_text(strategy_code)
        self._run(["git", "add", "strategy.py"])

        status = "ACCEPTED" if accepted else "rejected"
        sharpe_str = f"{val_sharpe:.2f}" if val_sharpe is not None else "N/A"
        msg = (
            f"iter {iteration} [{status}]: brier={val_brier:.4f} sharpe={sharpe_str}\n\n"
            f"Hypothesis: {hypothesis}"
        )
        self._run(["git", "commit", "-m", msg, "--allow-empty"])

        if accepted:
            tag = f"iter-{iteration:04d}-brier-{val_brier:.4f}"
            self._run(["git", "tag", tag])

        commit_hash = self._run(["git", "rev-parse", "HEAD"]).strip()
        return commit_hash

    def get_best_iteration(self) -> Optional[dict]:
        """Find the tag with the lowest Brier score."""
        result = self._run(["git", "tag", "-l", "iter-*"])
        tags = result.strip().split("\n")
        tags = [t.strip() for t in tags if t.strip()]

        if not tags:
            return None

        best_tag = None
        best_brier = float("inf")

        for tag in tags:
            # Parse: iter-0042-brier-0.1823
            parts = tag.split("-")
            try:
                brier = float(parts[-1])
                iteration = int(parts[1])
                if brier < best_brier:
                    best_brier = brier
                    best_tag = tag
            except (ValueError, IndexError):
                continue

        if best_tag is None:
            return None

        # Get the strategy code from that tag
        code = self._run(["git", "show", f"{best_tag}:strategy.py"])
        return {
            "tag": best_tag,
            "brier": best_brier,
            "code": code,
        }

    def get_strategy_at(self, ref: str) -> str:
        """Get strategy.py content at a specific git ref."""
        return self._run(["git", "show", f"{ref}:strategy.py"])

    def _run(self, cmd: list[str]) -> str:
        """Run a git command in the repo directory."""
        result = subprocess.run(
            cmd,
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 and result.stderr.strip():
            logger.warning("git %s stderr: %s", cmd[1], result.stderr.strip())
        return result.stdout
