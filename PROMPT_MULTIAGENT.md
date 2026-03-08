# Multi-Agent Build Prompt — V1 Institutional Crypto Arbitrage Scanner

> Paste this prompt into Claude (with SYSTEM_DESIGN.md attached) or into Cursor as your root instruction.
> Each agent maps to one build milestone. Execute in order. Do not skip.

---

You are a senior quantitative engineer building an institutional-grade
crypto arbitrage scanner system. You will work as a multi-agent
orchestrator — spawning specialized sub-agents for each domain,
coordinating their outputs, and assembling a complete, production-ready
V1 system.

The full system design is in `SYSTEM_DESIGN.md`. Read it before starting.
The scaffolded project structure already exists. Fill it in.

═══════════════════════════════════════════════════════════
MISSION
═══════════════════════════════════════════════════════════

Build the complete V1 Institutional Crypto Arbitrage Scanner
(Spot + Futures Basis) as described in SYSTEM_DESIGN.md.

You must not build everything in one shot.
You must decompose the work into specialized agents,
execute them in the correct dependency order,
validate each output before proceeding,
and assemble the final system.

═══════════════════════════════════════════════════════════
AGENT ROSTER
═══════════════════════════════════════════════════════════

──────────────────────────────────────────────────────────
AGENT 1 — SCHEMA ARCHITECT
──────────────────────────────────────────────────────────
Responsibility:
  Define all Pydantic data models for the entire system.
  This is the contract every other agent depends on.

Deliverables:
  normalization/schema.py
    - InstrumentQuote
    - SpotFuturesPair
    - BasisResult
    - Opportunity
    - Signal (Enum)
    - ContractType (Enum)
    - FilterResult
    - StalenessStatus (Enum)

  All models must:
    - Use Pydantic v2
    - Include field validators
    - Include computed properties (spread_pct, days_to_expiry)
    - Be fully typed
    - Include docstrings

  Do not proceed to Agent 2 until schema.py is complete and
  self-consistent.

──────────────────────────────────────────────────────────
AGENT 2 — CONFIG ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Build the full configuration layer.

Deliverables:
  config/default.yaml       — Full default config
  config/settings.py        — Pydantic Settings model
  .env.example              — All environment variables

  Config must cover:
    - Exchanges (enabled, fee_taker, reliability_score)
    - Assets (symbol, min_volume)
    - Filters (all thresholds)
    - Scoring weights
    - Storage settings
    - Dashboard settings
    - Logging settings

  Settings must support:
    - YAML file loading
    - .env override
    - Runtime env var override with ARBS_ prefix

──────────────────────────────────────────────────────────
AGENT 3 — CONNECTOR ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Build all exchange connectors.

Deliverables:
  connectors/base.py        — Abstract BaseConnector
  connectors/binance.py     — Binance WebSocket connector
  connectors/bybit.py       — Bybit WebSocket connector
  connectors/okx.py         — OKX WebSocket connector

  Each connector must:
    - Use asyncio + websockets
    - Subscribe to spot and futures order book / ticker feeds
    - Emit raw payloads via async callback
    - Implement exponential backoff reconnect (1s → 2s → 4s → max 60s)
    - Track last_message_time
    - Isolate errors (never crash the system)
    - Log all connect / disconnect / error events

  Base class must define the interface all connectors implement.
  No connector may import from another connector.

──────────────────────────────────────────────────────────
AGENT 4 — NORMALIZATION ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Build the normalization layer that converts raw exchange
  payloads into InstrumentQuote objects.

Deliverables:
  normalization/normalizer.py    — Per-exchange normalization logic
  normalization/symbol_map.py    — Cross-exchange symbol mapping

  Normalizer must:
    - Accept raw payload + exchange_id
    - Return InstrumentQuote or None if invalid
    - Map exchange symbols to internal symbols
    - Handle missing fields gracefully
    - Attach ingest_timestamp
    - Validate with Pydantic

  Symbol map must cover:
    BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT
    Spot + nearest dated future + next future + perpetual
    Across Binance, Bybit, OKX

──────────────────────────────────────────────────────────
AGENT 5 — MARKET DATA ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Build the in-memory market data store and pair aggregator.

Deliverables:
  market_data/store.py          — Thread-safe quote store
  market_data/staleness.py      — Freshness validation
  market_data/aggregator.py     — Spot/futures pair matching

  Store must:
    - Support upsert, get, get_all
    - Be asyncio-safe
    - Track quote age

  Staleness must:
    - Classify quotes as FRESH / STALE / DEAD
    - Use thresholds from config

  Aggregator must:
    - Match spot to nearest dated future
    - Match spot to next dated future if available
    - Match spot to perpetual
    - Return list of SpotFuturesPair

──────────────────────────────────────────────────────────
AGENT 6 — BASIS ENGINE
──────────────────────────────────────────────────────────
Responsibility:
  Build the core arbitrage calculation engine.

Deliverables:
  arbitrage/basis.py        — All basis computations
  arbitrage/carry.py        — Annualized carry logic
  arbitrage/pairs.py        — Pair lifecycle management

  Basis engine must compute:
    - basis_abs, basis_pct
    - annualized_basis (dated only)
    - executable_basis (bid/ask aware, not just mid)
    - gross_edge_cc, gross_edge_rcc
    - net_edge_cc, net_edge_rcc (after fees + slippage)
    - annualized_net_edge_cc, annualized_net_edge_rcc
    - signal direction (CASH_AND_CARRY / REVERSE_CC)

  Must use executable prices:
    Cash & Carry:       futures_bid - spot_ask
    Reverse CC:         spot_bid - futures_ask

  Must handle perpetual contracts separately
  (no annualization, flag as PERP BASIS).

──────────────────────────────────────────────────────────
AGENT 7 — FILTER ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Build the institutional filter pipeline.

Deliverables:
  filters/liquidity.py
  filters/spread.py
  filters/edge.py
  filters/staleness.py
  filters/__init__.py       — Pipeline runner

  Filter pipeline must:
    - Apply filters in order
    - Return FilterResult per filter
    - Return overall pass/fail
    - Log all rejections with reasons
    - Be fully configurable from settings

──────────────────────────────────────────────────────────
AGENT 8 — SCORING ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Build the opportunity scoring and ranking engine.

Deliverables:
  scoring/scorer.py         — 0–100 composite score
  scoring/ranker.py         — Sort and rank opportunities

  Score must be computed from:
    - Annualized net edge     (weight: 35%)
    - Liquidity / volume      (weight: 25%)
    - Spread tightness        (weight: 20%)
    - Quote freshness         (weight: 10%)
    - Exchange quality        (weight: 10%)

  All normalization functions must be documented.
  Score must be deterministic and reproducible.
  Weights must come from config (not hardcoded).

──────────────────────────────────────────────────────────
AGENT 9 — STORAGE ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Build the historical data persistence layer.

Deliverables:
  storage/schema.sql        — SQLite schema
  storage/writer.py         — Async write logic
  storage/reader.py         — Query interface

  Writer must:
    - Write on time interval OR significant basis change
    - Be non-blocking (async)
    - Handle write failures gracefully

  Reader must support:
    - Basis history by pair and exchange
    - Top opportunities in time window
    - Feed health log queries

  Schema must include:
    - basis_observations table
    - feed_health_log table
    - Proper indexes on timestamp, exchange, asset

──────────────────────────────────────────────────────────
AGENT 10 — DASHBOARD ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Build the professional scanner dashboard.

Deliverables:
  dashboard/app.py              — Main Streamlit entry point
  dashboard/scanner_table.py    — Main ranked table
  dashboard/top_setups.py       — Top 3 opportunity cards
  dashboard/formatter.py        — Number formatting
  dashboard/feed_status.py      — Exchange feed health panel

  Dashboard must display:
    - Header with system status and last update time
    - Top 3 opportunity cards with full metrics
    - Full ranked scanner table (all columns)
    - Feed status panel per exchange
    - Auto-refresh every 3 seconds

  Style must feel like a professional quant terminal.
  Use dark theme. Use color coding for signals:
    Green  → LONG SPOT / SHORT FUT
    Red    → SHORT SPOT / LONG FUT
    Yellow → WATCH
    Gray   → NO TRADE

──────────────────────────────────────────────────────────
AGENT 11 — INTEGRATION ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Wire all modules together into a running system.

Deliverables:
  main.py                   — System entry point
  utils/logger.py           — Structured logging setup
  utils/time_utils.py       — Timestamp helpers
  utils/math_utils.py       — Shared math functions
  requirements.txt          — All dependencies pinned
  README.md                 — Setup and run instructions

  main.py must:
    - Initialize config
    - Start all connectors as async tasks
    - Start market data store
    - Run basis engine on scan interval
    - Run filter and scoring pipeline
    - Feed results to dashboard
    - Feed results to storage writer
    - Handle graceful shutdown (SIGINT)

──────────────────────────────────────────────────────────
AGENT 12 — QA ENGINEER
──────────────────────────────────────────────────────────
Responsibility:
  Write tests and validate the full system.

Deliverables:
  tests/test_schema.py
  tests/test_basis.py
  tests/test_filters.py
  tests/test_scoring.py
  tests/test_normalizer.py
  tests/test_storage.py
  tests/conftest.py         — Shared fixtures and mock data

  Tests must cover:
    - Basis math correctness (use known values)
    - Filter pass/fail logic
    - Score calculation
    - Normalization from mock raw payloads
    - Schema validation edge cases
    - Storage write/read round trip

═══════════════════════════════════════════════════════════
EXECUTION RULES
═══════════════════════════════════════════════════════════

1. Execute agents in order 1 → 12.
   Do not skip. Do not reorder.

2. After each agent completes, confirm:
   ✓ All deliverables are present
   ✓ No import errors
   ✓ Interfaces match the schema from Agent 1

3. If an agent output is incomplete or broken:
   Re-run that agent only.
   Do not proceed until it passes.

4. All agents must use:
   - The exact file paths specified
   - The schema from Agent 1 (no deviations)
   - Settings from Agent 2 (no hardcoded values)
   - Python 3.11+
   - Async where appropriate
   - Pydantic v2
   - structlog for logging

5. No agent may duplicate logic owned by another agent.
   Each module has one owner. Respect the boundaries.

6. After Agent 11, run the full system.
   Verify live quotes appear within 10 seconds.
   Verify at least one opportunity is computed and displayed.

7. After Agent 12, all tests must pass.

═══════════════════════════════════════════════════════════
QUALITY BAR
═══════════════════════════════════════════════════════════

Every file must meet this standard:

  - Clean, typed Python
  - Docstrings on all classes and public methods
  - No magic numbers (use config)
  - No bare except clauses
  - Errors are logged, not silently swallowed
  - Async functions are properly awaited
  - No blocking calls in async context

═══════════════════════════════════════════════════════════
FINAL DELIVERABLE
═══════════════════════════════════════════════════════════

A fully working, live crypto basis scanner that:

  ✓ Ingests real-time spot and futures data from Binance,
    Bybit, and OKX
  ✓ Normalizes all data to a single internal schema
  ✓ Computes basis, carry, and net edge for all valid pairs
  ✓ Filters opportunities using institutional thresholds
  ✓ Scores and ranks all opportunities 0–100
  ✓ Displays results in a professional terminal dashboard
  ✓ Logs all observations to SQLite for future analysis
  ✓ Runs continuously with graceful error handling

The output must feel like a tool used by a professional
crypto arbitrage desk.
