"""
Module C: Agent Sandbox.

Validates and executes LLM-generated strategy code in an isolated subprocess.
The strategy is NEVER exec'd in the orchestrator process.

Security layers:
  1. AST-based static analysis (import whitelist, blocked builtins)
  2. Subprocess isolation with timeout
  3. Working directory in /tmp (no access to project files)
"""
from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from textwrap import dedent
from typing import Optional

logger = logging.getLogger(__name__)

# Modules the generated strategy is allowed to import
ALLOWED_TOP_LEVEL_MODULES = frozenset({
    "pandas", "pd",
    "numpy", "np",
    "sklearn", "scikit-learn",
    "scipy",
    "math",
    "statistics",
    "collections",
    "functools",
    "itertools",
    "operator",
    "dataclasses",
    "typing",
    "datetime",
    "json",
    "re",
    "copy",
    "abc",
})

# Builtins that must never appear as function calls
BLOCKED_BUILTINS = frozenset({
    "open", "exec", "eval", "compile", "__import__",
    "breakpoint", "exit", "quit", "input",
})

# Modules that must never be imported
BLOCKED_MODULES = frozenset({
    "os", "sys", "subprocess", "socket", "http",
    "urllib", "requests", "httpx", "aiohttp",
    "shutil", "pathlib", "glob", "io",
    "ctypes", "multiprocessing", "threading",
    "signal", "pickle", "shelve", "sqlite3",
    "importlib", "builtins", "code", "codeop",
})


def validate_strategy_source(code: str) -> list[str]:
    """
    Static analysis of strategy source code.

    Returns list of error strings. Empty list means code is safe to run.
    """
    errors = []

    # Step 1: syntax check
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        errors.append(f"SyntaxError at line {e.lineno}: {e.msg}")
        return errors

    # Step 2: check imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in BLOCKED_MODULES:
                    errors.append(f"Blocked import: {alias.name} (line {node.lineno})")
                elif top not in ALLOWED_TOP_LEVEL_MODULES:
                    errors.append(f"Disallowed import: {alias.name} (line {node.lineno})")

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in BLOCKED_MODULES:
                    errors.append(f"Blocked import: {node.module} (line {node.lineno})")
                elif top not in ALLOWED_TOP_LEVEL_MODULES:
                    errors.append(f"Disallowed import: {node.module} (line {node.lineno})")

        # Step 3: check blocked builtin calls
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BLOCKED_BUILTINS:
                errors.append(f"Blocked call: {func.id}() (line {node.lineno})")
            elif isinstance(func, ast.Attribute) and func.attr in BLOCKED_BUILTINS:
                errors.append(f"Blocked call: .{func.attr}() (line {node.lineno})")

    # Step 4: check that predict() function exists
    has_predict = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "predict":
            has_predict = True
            break
    if not has_predict:
        errors.append("Missing required function: predict(row)")

    return errors


# The runner script is written to a temp file and executed in a subprocess.
# It imports the strategy, iterates rows, and writes predictions to stdout.
_RUNNER_TEMPLATE = dedent("""\
    import json
    import sys
    import traceback

    # Load strategy module
    sys.path.insert(0, "{sandbox_dir}")
    try:
        import strategy
    except Exception as e:
        print(json.dumps({{"error": f"Import error: {{e}}", "predictions": []}}))
        sys.exit(1)

    # Read input rows
    with open("{input_path}") as f:
        rows = json.load(f)

    predictions = []
    for i, row in enumerate(rows):
        try:
            result = strategy.predict(row)
            if not isinstance(result, dict):
                result = {{"action": "PASS", "fair_value": 0.5, "confidence": 0.0, "limit_price": None}}
            # Ensure required keys
            result.setdefault("action", "PASS")
            result.setdefault("fair_value", 0.5)
            result.setdefault("confidence", 0.0)
            result.setdefault("limit_price", None)
            predictions.append(result)
        except Exception as e:
            predictions.append({{
                "action": "PASS",
                "fair_value": 0.5,
                "confidence": 0.0,
                "limit_price": None,
                "error": f"Row {{i}}: {{e}}",
            }})

    print(json.dumps({{"error": None, "predictions": predictions}}))
""")


def execute_strategy(
    strategy_code: str,
    data_rows: list[dict],
    timeout_seconds: int = 60,
    sandbox_dir: str = "/tmp/autoresearch_sandbox",
) -> tuple[list[dict], str, float]:
    """
    Execute a strategy in an isolated subprocess.

    Args:
        strategy_code: Python source code with a predict(row) function.
        data_rows: List of dicts, one per timestamp to evaluate.
        timeout_seconds: Max execution time before kill.
        sandbox_dir: Working directory for the subprocess.

    Returns:
        (predictions, error_log, elapsed_seconds)
        predictions is a list of dicts with action/fair_value/confidence/limit_price.
        error_log is stderr output or timeout message.
    """
    sandbox = Path(sandbox_dir)
    sandbox.mkdir(parents=True, exist_ok=True)

    # Write strategy module
    strategy_path = sandbox / "strategy.py"
    strategy_path.write_text(strategy_code)

    # Write input data
    input_path = sandbox / "input.json"
    # Convert non-serializable types
    clean_rows = _sanitize_rows(data_rows)
    with open(input_path, "w") as f:
        json.dump(clean_rows, f)

    # Write runner script
    runner_path = sandbox / "_runner.py"
    runner_code = _RUNNER_TEMPLATE.format(
        sandbox_dir=str(sandbox),
        input_path=str(input_path),
    )
    runner_path.write_text(runner_code)

    # Execute in subprocess
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, str(runner_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(sandbox),
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", "/tmp"),
                "PYTHONPATH": "",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        elapsed = time.monotonic() - t0

        stderr_log = result.stderr.strip()
        if result.returncode != 0:
            return [], stderr_log or f"Process exited with code {result.returncode}", elapsed

        # Parse stdout
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            return [], f"Invalid JSON output: {result.stdout[:500]}", elapsed

        error = output.get("error")
        predictions = output.get("predictions", [])

        if error:
            return predictions, error, elapsed

        return predictions, stderr_log, elapsed

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        return [], f"TIMEOUT after {timeout_seconds}s", elapsed


def _sanitize_rows(rows: list[dict]) -> list[dict]:
    """Convert non-JSON-serializable values in data rows."""
    import datetime as dt

    clean = []
    for row in rows:
        clean_row = {}
        for k, v in row.items():
            if isinstance(v, (dt.date, dt.datetime)):
                clean_row[k] = v.isoformat()
            elif hasattr(v, "item"):  # numpy scalar
                clean_row[k] = v.item()
            elif v is None or isinstance(v, (int, float, str, bool)):
                clean_row[k] = v
            else:
                clean_row[k] = str(v)
        clean.append(clean_row)
    return clean
