# Kalshi Trading Bot

[![CI](https://github.com/karshincheo/kalshi-trading/actions/workflows/ci.yml/badge.svg)](https://github.com/karshincheo/kalshi-trading/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An autonomous prediction market trading system for [Kalshi](https://kalshi.com): five trading strategies with paper-trading support, plus an LLM-driven research loop that writes, backtests, and evolves temperature-market strategies overnight.

> **Provenance:** built locally over several weeks and imported in one commit; now developed in the open, so the history starts thin. This repo contains the Python backend — the monitoring dashboard lives in a private deployment.

---

## Architecture

```
backend/                        # FastAPI trading bot + autoresearch engine
└── app/
    ├── autoresearch/           # Autonomous Climate Quant Researcher
    ├── broker/                 # Kalshi API client + PaperBroker simulator
    ├── core/
    │   ├── strategies/         # 5 trading strategies
    │   ├── math/               # Kelly, DEPO, HRP, Brier metrics
    │   └── risk/               # Circuit breakers
    ├── services/               # Trading engine, backtester, portfolio
    └── api/                    # REST + WebSocket endpoints
```

---

## Trading Strategies

| Strategy | Edge | Status |
|----------|------|--------|
| **Longshot Bias** | Markets overprice extreme probabilities (95-99¢ YES). Regression-to-mean generates ~4% edge. | Enabled by default |
| **Avellaneda-Stoikov Market Making** | Two-sided liquidity with jump-diffusion adjustment near resolution. Earn the bid-ask spread. | Configurable |
| **Nowcasting** | BLS/FRED real-time data predicts CPI, jobs, Fed rate outcomes before official release. | Configurable |
| **Cross-Market Arbitrage** | Kalshi vs Polymarket price discrepancies on identical events. | Configurable |
| **LIP Optimizer** | Optimizes for Kalshi's Liquidity Incentive Program rewards. | Configurable |

All strategies extend `AbstractStrategy`, produce `Signal` objects, and are sized via Kelly criterion + DEPO portfolio optimization.

---

## Autonomous Climate Quant Researcher

The `app/autoresearch/` module implements an LLM-driven research loop that automatically writes, backtests, and evolves trading strategies for Kalshi's daily temperature prediction markets.

```
┌──────────────────────────────────────────────────────────┐
│                     RESEARCH LOOP                         │
│                                                          │
│  Collect Kalshi data → Build dataset (Kalshi + weather)  │
│       ↓                                                  │
│  Evaluate current strategy → Prompt Claude               │
│       ↓                                                  │
│  Extract code → Validate (AST) → Sandbox execution       │
│       ↓                                                  │
│  Score (Brier + Sharpe) → Accept/reject → Git commit     │
│       ↓                                                  │
│  Repeat for N iterations                                 │
└──────────────────────────────────────────────────────────┘
```

**Optimization target:** [Brier Score](https://en.wikipedia.org/wiki/Brier_score) (probability calibration) on out-of-sample validation data. Secondary: Sharpe Ratio > 1.5.

**Anti-overfitting:** Strict train/val/holdout split by `target_date`. The agent never sees holdout data. Final evaluation is manual, one-shot.

**Containment (defense-in-depth, not a security boundary):** generated code passes an AST pre-filter (import whitelist, blocked builtins) and runs in an isolated subprocess with a 60-second timeout. The AST pass alone is bypassable by dynamic-attribute escapes — [the test suite pins this explicitly](backend/app/tests/unit/test_sandbox_validator.py); the subprocess layer is what bounds buggy generated code, and truly hostile code would need a real jail.

---

## AI tooling & techniques

- **Model:** Claude (Sonnet) via the Anthropic API writes the candidate strategy code on every research iteration.
- **Closed-loop code generation with guardrails:** prompt → extract code → AST validation → sandboxed backtest → accept/reject on score → git commit. Every accepted strategy lands as a commit, so the model's progress has a full audit trail.
- **Evals as the optimization target:** the loop optimizes out-of-sample Brier score with a Sharpe gate — measured calibration on data the model never trained against, not subjective judgment of generated code.

---

## Quickstart

### Prerequisites
- Python 3.11+

### Backend

```bash
cd backend

# Install dependencies
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env — set BROKER_MODE=paper to start (no API keys needed)

# Run database migrations
python -m alembic upgrade head

# Start the server
python start_server.py
# or: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Backend runs at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

### Troubleshooting

- `unable to open database file` — the SQLite data directory is created on first
  run; if you see this from alembic, run `mkdir -p data` inside `backend/` first.
- `BackendUnavailable` from pip — upgrade pip/setuptools (`pip install -U pip setuptools`).
- No API keys are needed in `BROKER_MODE=paper`; live mode requires Kalshi credentials in `.env`.

---

## Autoresearch CLI

**Try the evaluator with zero API keys** — a real collected dataset (185 temperature-market
snapshots + weather features) is bundled:

```bash
make demo   # from the repo root; offline, no keys
```

```
Sample set: 185 rows
Brier Score:  0.0828  (market-implied baseline: 0.0828 — lower is better)
```

The seed strategy scores exactly the market baseline — by design, it tracks the
market's implied probability. That's the starting line: the research loop's job is
to evolve a strategy whose out-of-sample Brier beats it.

The full loop:

```bash
cd backend

# Step 1: Start collecting Kalshi temperature market data
python -m app.autoresearch collect
# Runs every 5 minutes, stores Parquet snapshots to data/autoresearch/kalshi_cache/

# Step 2: Run the optimization loop (requires Anthropic API key)
export AUTORESEARCH_ANTHROPIC_API_KEY=sk-ant-...
python -m app.autoresearch run --iterations 100 --model claude-sonnet-4-20250514

# Step 3: Evaluate best strategy on holdout set
python -m app.autoresearch evaluate data/autoresearch/iterations/best_strategy.py
```

**Model options:**
- `claude-sonnet-4-20250514` — fast, ~$0.01-0.03/iter (default, good for 1000-run overnight research)
- `claude-opus-4-20250514` — highest quality, ~$0.15-0.30/iter (use for early exploration)

---

## Configuration

All settings are loaded from environment variables (prefix `AUTORESEARCH_` for the research module):

| Variable | Default | Description |
|----------|---------|-------------|
| `BROKER_MODE` | `paper` | `paper` / `demo` / `live` |
| `PAPER_INITIAL_BALANCE` | `10000` | Starting virtual balance |
| `AUTORESEARCH_ANTHROPIC_API_KEY` | — | Anthropic API key for the research loop |
| `AUTORESEARCH_ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | LLM model |
| `AUTORESEARCH_MAX_ITERATIONS` | `1000` | Research loop iterations |
| `AUTORESEARCH_TARGET_BRIER` | `0.15` | Stop when Brier score reaches this |
| `AUTORESEARCH_SANDBOX_TIMEOUT_SECONDS` | `60` | Max strategy execution time |
| `AUTORESEARCH_MAX_DAILY_SPEND` | `50.0` | Live trading daily cap (Phase 3) |

---

## Rollout Phases

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 1: Dry Run** | Run research loop for 1,000 epochs on collected data. Verify continuous operation. | In progress |
| **Phase 2: Paper Trading** | Best strategy runs on live feed, logs intended trades, no capital. | Planned |
| **Phase 3: Live ($50/day)** | Connect Kalshi API, cap daily exposure to $50 to monitor real-world slippage. | Planned |

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/autoresearch/loop.py` | Orchestrator — drives the LLM research loop |
| `backend/app/autoresearch/evaluate.py` | Backtesting engine — immutable, runs strategies via sandbox |
| `backend/app/autoresearch/prepare.py` | Data pipeline — merges Kalshi + Open-Meteo weather data |
| `backend/app/autoresearch/sandbox.py` | Safe execution — AST validation + subprocess isolation |
| `backend/app/autoresearch/program.md` | LLM system prompt — strategy interface contract |
| `backend/app/core/strategies/` | Five live trading strategies |
| `backend/app/services/trading_engine.py` | Signal → Kelly sizing → circuit breaker → order |
| `backend/app/services/backtest_engine.py` | Walk-forward backtester (López de Prado methodology) |
| `backend/app/broker/paper_broker.py` | Paper trading simulator with slippage + fee modeling |
