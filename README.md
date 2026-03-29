# Kalshi Trading Bot

An autonomous prediction market trading system for [Kalshi](https://kalshi.com), combining five production-grade trading strategies with an LLM-driven research loop that self-improves temperature market strategies overnight.

---

## Architecture

```
kalshi-trading/
├── backend/                    # FastAPI trading bot + autoresearch engine
│   └── app/
│       ├── autoresearch/       # Autonomous Climate Quant Researcher
│       ├── broker/             # Kalshi API client + PaperBroker simulator
│       ├── core/
│       │   ├── strategies/     # 5 live trading strategies
│       │   ├── math/           # Kelly, DEPO, HRP, Brier metrics
│       │   └── risk/           # Circuit breakers
│       ├── services/           # Trading engine, backtester, portfolio
│       └── api/                # REST + WebSocket endpoints
└── frontend/                   # Next.js dashboard
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

**Security:** Generated code is AST-validated (import whitelist, blocked builtins) and runs in an isolated subprocess in `/tmp/` with a 60-second timeout.

---

## Quickstart

### Prerequisites
- Python 3.11+
- Node.js 18+ (frontend only)

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

### Frontend

```bash
cd frontend
npm install
npm run dev
# Runs at http://localhost:3001
```

---

## Autoresearch CLI

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
