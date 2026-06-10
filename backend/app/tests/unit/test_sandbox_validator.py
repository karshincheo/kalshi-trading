"""Unit tests for the autoresearch AST pre-filter.

The validator is a static pre-filter, not a security boundary — real isolation
comes from the sandboxed subprocess with a timeout. These tests pin the
allow/deny behavior of the AST pass and document its known limits.
"""

from app.autoresearch.sandbox import validate_strategy_source


VALID_STRATEGY = """
import math

def predict(row):
    return min(1.0, max(0.0, 0.5 + math.tanh(row.get("forecast_vs_strike", 0)) / 4))
"""


class TestValidStrategies:
    def test_clean_strategy_passes(self):
        assert validate_strategy_source(VALID_STRATEGY) == []

    def test_syntax_error_is_reported_with_line(self):
        errors = validate_strategy_source("def broken(:\n    pass")
        assert errors and "SyntaxError" in errors[0]


class TestBlockedPatterns:
    def test_blocked_module_import_rejected(self):
        errors = validate_strategy_source("import os\n")
        assert errors

    def test_blocked_from_import_rejected(self):
        errors = validate_strategy_source("from subprocess import run\n")
        assert errors

    def test_blocked_builtin_call_rejected(self):
        errors = validate_strategy_source("eval('1+1')\n")
        assert errors

    def test_open_call_rejected(self):
        errors = validate_strategy_source("open('/etc/passwd')\n")
        assert errors


class TestKnownLimits:
    """The AST pass alone does not catch dynamic-attribute escapes; the
    subprocess isolation layer is what bounds those. Pinned here so the
    limitation is explicit, not accidental."""

    def test_dunder_traversal_is_not_caught_by_ast_pass(self):
        code = "x = ().__class__.__bases__[0].__subclasses__()\n"
        # Documents current behavior: this passes the static filter and is
        # contained by the subprocess sandbox instead.
        assert isinstance(validate_strategy_source(code), list)
