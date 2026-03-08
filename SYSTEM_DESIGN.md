# V1 Institutional Crypto Arbitrage Scanner
### Spot & Futures Basis — System Design & Engineering Reference

---

## Table of Contents

1. [Overview](#overview)
2. [Design Philosophy](#design-philosophy)
3. [Scope & Boundaries](#scope--boundaries)
4. [Architecture Overview](#architecture-overview)
5. [Project Structure](#project-structure)
6. [Module Specifications](#module-specifications)
   - [Connectors](#1-connectors)
   - [Normalization](#2-normalization)
   - [Market Data](#3-market-data)
   - [Arbitrage Engine](#4-arbitrage-engine)
   - [Filters](#5-filters)
   - [Scoring](#6-scoring)
   - [Dashboard](#7-dashboard)
   - [Storage](#8-storage)
   - [Config](#9-config)
7. [Data Schema](#data-schema)
8. [Basis Calculation Logic](#basis-calculation-logic)
9. [Opportunity Detection Rules](#opportunity-detection-rules)
10. [Scoring Model](#scoring-model)
11. [Dashboard Specification](#dashboard-specification)
12. [Storage Layer](#storage-layer)
13. [Tech Stack](#tech-stack)
14. [Reliability Requirements](#reliability-requirements)
15. [Configuration Reference](#configuration-reference)
16. [Build Order & Milestones](#build-order--milestones)
17. [Future Expansion Roadmap](#future-expansion-roadmap)

---

## Overview

The V1 Institutional Crypto Arbitrage Scanner is a **production-style infrastructure layer** designed to reliably detect and rank spot vs. futures basis opportunities across major crypto exchanges.

This is not yet a trading system. It is the **foundation** of a broader arbitrage platform.

### Core Objective

Continuously scan selected crypto markets, detect spot vs. futures mispricings, compute the carry, apply institutional-grade cost and liquidity filters, and rank the best opportunities in a professional terminal-style dashboard.

### What the Scanner Does

```
INGEST → NORMALIZE → COMPUTE BASIS → FILTER → SCORE → DISPLAY → LOG
```

For each asset/exchange pair:
- Compare spot price to futures price
- Compute absolute basis, percentage basis, and annualized carry
- Apply liquidity and cost filters
- Rank opportunities by attractiveness
- Identify trade structure: **Buy Spot / Sell Futures** or **Sell Spot / Buy Futures**
- Log all observations for future analysis

---

## Design Philosophy

> **Simple. Robust. Modular. Scalable. Professional. Data-first.**

| Principle | Implementation |
|-----------|---------------|
| **Simple** | No overengineering. Clean interfaces between modules. |
| **Robust** | Handles reconnects, stale data, bad feeds without crashing. |
| **Modular** | Each module is independently testable and replaceable. |
| **Scalable** | Easy to add exchanges, assets, and new arb types. |
| **Professional** | Institutional-quality data handling, logging, and output. |
| **Data-first** | Reliable ingestion and normalization before any analytics. |

The priority is a **reliable core**. Do not sacrifice robustness for features.

---

## Scope & Boundaries

### V1 Includes

- Spot market data ingestion
- Dated futures data ingestion
- Perpetual futures (secondary, for comparison)
- Real-time basis computation
- Opportunity detection and ranking
- Terminal/dashboard-style UI
- Historical basis logging

### V1 Explicitly Excludes

| Feature | Reason |
|---------|--------|
| Options arbitrage | Requires volatility surface — V2+ |
| Machine learning | No signal history yet — V3+ |
| Execution engine | Requires risk controls — V2+ |
| Auto order placement | Requires execution infra — V2+ |
| Advanced portfolio optimization | Requires position management — V3+ |
| Funding rate deep-dive | Secondary in V1, dedicated in V2 |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        CONFIG LAYER                          │
│        exchanges, assets, thresholds, fees, intervals        │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
      ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
      │  Binance     │ │  Bybit       │ │  OKX         │
      │  Connector   │ │  Connector   │ │  Connector   │
      └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
             │                │                │
             └────────────────┼────────────────┘
                              ▼
                   ┌─────────────────────┐
                   │   NORMALIZATION      │
                   │  (exchange-agnostic  │
                   │   internal schema)   │
                   └──────────┬──────────┘
                              │
                   ┌──────────▼──────────┐
                   │   MARKET DATA BUS    │
                   │  (in-memory store +  │
                   │   staleness checks)  │
                   └──────────┬──────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │   BASIS       │  │   FILTERS    │  │   SCORING    │
    │   ENGINE      │  │              │  │              │
    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
           └────────────────►│◄─────────────────┘
                             ▼
                   ┌─────────────────────┐
                   │  OPPORTUNITY RANKER  │
                   └──────────┬──────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  DASHBOARD   │  │   STORAGE    │  │   LOGGER     │
    │  (Streamlit) │  │  (SQLite /   │  │  (errors,    │
    │              │  │   Parquet)   │  │   events)    │
    └──────────────┘  └──────────────┘  └──────────────┘
```

### Key Design Decisions

- **Async-first**: All connectors use `asyncio` + `websockets` for non-blocking I/O
- **Exchange-agnostic core**: Normalization layer decouples analytics from exchange specifics
- **Fail-safe per feed**: A bad connector never crashes the system; errors are logged and retried
- **Separation of concerns**: Data ingestion is fully separate from analytics and display

---

## Project Structure

```
arbitrage_scanner/
│
├── connectors/                  # Exchange-specific data adapters
│   ├── __init__.py
│   ├── base.py                  # Abstract base connector class
│   ├── binance.py               # Binance spot + futures connector
│   ├── bybit.py                 # Bybit spot + futures connector
│   └── okx.py                  # OKX spot + futures connector
│
├── normalization/               # Raw → internal schema conversion
│   ├── __init__.py
│   ├── schema.py                # Pydantic models (InstrumentQuote, etc.)
│   ├── normalizer.py            # Per-exchange normalization logic
│   └── symbol_map.py            # Cross-exchange symbol mapping
│
├── market_data/                 # Central data store and management
│   ├── __init__.py
│   ├── store.py                 # In-memory market data store
│   ├── staleness.py             # Quote freshness validation
│   └── aggregator.py           # Pair matching (spot ↔ futures)
│
├── arbitrage/                   # Basis computation engine
│   ├── __init__.py
│   ├── basis.py                 # Core basis calculations
│   ├── carry.py                 # Annualized carry logic
│   └── pairs.py                 # Spot/futures pair management
│
├── filters/                     # Institutional-grade opportunity filters
│   ├── __init__.py
│   ├── liquidity.py             # Volume and depth filters
│   ├── spread.py                # Bid/ask spread filters
│   ├── edge.py                  # Net edge after fees/slippage
│   └── staleness.py             # Data freshness filter
│
├── scoring/                     # Opportunity scoring engine
│   ├── __init__.py
│   ├── scorer.py                # 0–100 composite score
│   └── ranker.py                # Sort and rank opportunities
│
├── dashboard/                   # Terminal / Streamlit UI
│   ├── __init__.py
│   ├── app.py                   # Main Streamlit app entry point
│   ├── scanner_table.py         # Main opportunities table
│   ├── top_setups.py            # Top opportunities panel
│   └── formatter.py             # Number formatting helpers
│
├── storage/                     # Historical data persistence
│   ├── __init__.py
│   ├── writer.py                # Write basis observations
│   ├── reader.py                # Query historical data
│   └── schema.sql               # SQLite schema definition
│
├── config/                      # Configuration management
│   ├── __init__.py
│   ├── settings.py              # Pydantic settings model
│   └── default.yaml             # Default configuration file
│
├── utils/                       # Shared utilities
│   ├── __init__.py
│   ├── logger.py                # Structured logging setup
│   ├── time_utils.py            # Timestamp helpers
│   └── math_utils.py            # Shared math functions
│
├── tests/                       # Unit and integration tests
│   ├── test_basis.py
│   ├── test_filters.py
│   ├── test_normalizer.py
│   └── test_scoring.py
│
├── main.py                      # System entry point
├── requirements.txt
├── README.md
└── .env.example
```

---

## Module Specifications

### 1. Connectors

**Purpose:** Ingest raw market data from each exchange via WebSocket or REST polling. Shield the rest of the system from exchange-specific quirks.

**Interface (base.py):**

```python
class BaseConnector(ABC):
    exchange_id: str

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def subscribe(self, symbols: List[str]) -> None: ...
    async def on_quote(self, callback: Callable) -> None: ...
    async def reconnect(self) -> None: ...

    @property
    def is_connected(self) -> bool: ...
    @property
    def last_message_time(self) -> datetime: ...
```

**Per-Exchange Responsibilities:**

| Exchange | Spot Feed | Futures Feed | Auth Required |
|----------|-----------|--------------|---------------|
| Binance | `wss://stream.binance.com` | `wss://fstream.binance.com` | No (public) |
| Bybit | `wss://stream.bybit.com/v5` | Same endpoint, different category | No (public) |
| OKX | `wss://ws.okx.com:8443/ws/v5/public` | Same endpoint, instType=FUTURES | No (public) |

**Reliability Behavior:**
- Exponential backoff on reconnect (1s → 2s → 4s → max 60s)
- Heartbeat/ping every 30 seconds
- Log every disconnect and reconnect event
- Never propagate exceptions to the rest of the system — catch, log, retry

---

### 2. Normalization

**Purpose:** Convert raw exchange-specific payloads into a single internal schema. After this layer, no module knows or cares which exchange the data came from.

**symbol_map.py** handles cross-exchange naming differences:

```
Binance:   BTCUSDT / BTCUSDT_241227
Bybit:     BTCUSDT / BTC-27DEC24
OKX:       BTC-USDT / BTC-USDT-241227
Internal:  BTC/USDT SPOT / BTC/USDT FUT 2024-12-27
```

**Key normalization steps:**
1. Parse raw ticker/book event
2. Map to internal symbol
3. Fill required fields, mark optional fields as `None` if missing
4. Attach exchange ID and `ingest_timestamp`
5. Validate with Pydantic model
6. Emit normalized `InstrumentQuote`

---

### 3. Market Data

**Purpose:** Maintain a live, in-memory snapshot of all current quotes. Provide pair-matching between spot and futures instruments.

**store.py:**
- Thread-safe dict keyed by `(exchange, internal_symbol)`
- `upsert(quote: InstrumentQuote)` → update or insert
- `get(exchange, symbol)` → returns latest quote or `None`
- `get_all()` → returns full snapshot

**staleness.py:**
- Each quote has a `staleness_status`: `FRESH` / `STALE` / `DEAD`
- `STALE` threshold: configurable (default 5s)
- `DEAD` threshold: configurable (default 30s)
- Stale quotes are used but flagged; dead quotes are excluded

**aggregator.py:**
- Finds all valid spot/futures pairs
- Emits `SpotFuturesPair` objects for the arbitrage engine
- Handles: nearest expiry, next expiry, perpetual

---

### 4. Arbitrage Engine

**Purpose:** Compute all basis metrics for each valid spot/futures pair.

**basis.py — Core Calculations:**

```python
@dataclass
class BasisResult:
    exchange: str
    asset: str
    spot_symbol: str
    futures_symbol: str
    contract_type: ContractType       # DATED | PERPETUAL
    expiry: Optional[date]
    days_to_expiry: Optional[float]

    spot_bid: float
    spot_ask: float
    spot_mid: float

    futures_bid: float
    futures_ask: float
    futures_mid: float

    # Mid-based
    basis_abs: float                  # futures_mid - spot_mid
    basis_pct: float                  # basis_abs / spot_mid
    annualized_basis: Optional[float] # basis_pct * 365 / dte

    # Executable (bid/ask aware)
    executable_basis_cc: float        # sell futures_bid - buy spot_ask
    executable_basis_rcc: float       # sell spot_bid - buy futures_ask

    gross_edge_cc_pct: float          # executable_basis_cc / spot_ask
    gross_edge_rcc_pct: float         # executable_basis_rcc / spot_bid

    net_edge_cc_pct: float            # gross minus fees and slippage
    net_edge_rcc_pct: float

    annualized_net_edge_cc: Optional[float]
    annualized_net_edge_rcc: Optional[float]

    signal: Signal                    # CASH_AND_CARRY | REVERSE_CC | WATCH | NO_TRADE
    timestamp: datetime
```

**Executable Basis Formula:**

```
Cash & Carry:
  executable_basis = futures_bid - spot_ask
  → "I buy spot at ask, sell futures at bid"

Reverse Cash & Carry:
  executable_basis = spot_bid - futures_ask
  → "I sell spot at bid, buy futures at ask"
```

**Cost Model:**
```
net_edge = gross_edge - (2 × fee_rate) - (2 × slippage_assumption)
```

Default fee assumptions: `0.05%` taker per leg (configurable per exchange).

---

### 5. Filters

**Purpose:** Reject opportunities that don't meet institutional quality thresholds.

**Filter pipeline (applied in order):**

```
1. STALENESS FILTER    → reject if any leg has dead data
2. VOLUME FILTER       → reject if 24h volume < min_volume_usd
3. SPREAD FILTER       → reject if bid/ask spread > max_spread_pct
4. EDGE FILTER         → reject if net_edge_pct ≤ 0 after fees
5. BASIS FILTER        → reject if annualized_basis < min_annual_basis
6. DEPTH FILTER        → warn if order book depth unavailable
```

Each filter returns a `FilterResult(passed: bool, reason: str)`. All failed filters are logged for diagnostics.

**Filter Config:**

```yaml
filters:
  min_annualized_basis: 0.05        # 5% annualized minimum
  min_volume_usd_24h: 1_000_000     # $1M minimum 24h volume
  max_spread_pct: 0.001             # 0.1% max bid/ask spread
  max_staleness_seconds: 5          # 5s max quote age
  fee_rate_per_leg: 0.0005          # 0.05% taker fee
  slippage_assumption: 0.0003       # 0.03% slippage per leg
```

---

### 6. Scoring

**Purpose:** Assign each opportunity a composite score from 0 to 100.

**Scoring Weights:**

| Factor | Weight | Description |
|--------|--------|-------------|
| Annualized net edge | 35% | Core profitability metric |
| Liquidity (volume) | 25% | Ease of execution |
| Spread tightness | 20% | Market quality / cost certainty |
| Quote freshness | 10% | Data reliability |
| Exchange quality | 10% | Exchange reliability rating |

**Score Computation:**

```python
def compute_score(opportunity: BasisResult, config: Config) -> float:
    edge_score      = normalize(opportunity.annualized_net_edge_cc, 0, 0.30) * 35
    liquidity_score = normalize(log(opportunity.volume_usd), log(1e6), log(1e9)) * 25
    spread_score    = normalize(1 - opportunity.spread_pct, 0.999, 1.0) * 20
    freshness_score = normalize(1 - staleness_ratio, 0, 1) * 10
    exchange_score  = EXCHANGE_QUALITY_RATINGS[opportunity.exchange] * 10
    return min(100, edge_score + liquidity_score + spread_score + freshness_score + exchange_score)
```

**Score Interpretation:**

| Score Range | Meaning |
|-------------|---------|
| 80–100 | Strong setup — worth serious attention |
| 60–79 | Decent opportunity — monitor closely |
| 40–59 | Marginal — likely not worth execution cost |
| 0–39 | Weak — display only, no trade signal |

---

### 7. Dashboard

**Purpose:** Display all ranked opportunities in a professional, terminal-style scanner UI.

**Technology:** Streamlit (with auto-refresh via `streamlit-autorefresh`)

**Main Scanner Table:**

| Column | Description |
|--------|-------------|
| Symbol | Asset (BTC, ETH, ...) |
| Exchange | Binance / Bybit / OKX |
| Spot | Current spot mid price |
| Futures | Current futures mid price |
| Expiry | Contract expiry date |
| DTE | Days to expiry |
| Basis | Absolute basis (USD) |
| Basis % | Percentage basis |
| Ann. Basis | Annualized carry % |
| Net Edge | Net edge after fees (ann.) |
| Volume | 24h volume (USD) |
| Spread | Futures bid/ask spread % |
| Score | Composite score 0–100 |
| Signal | Trade signal |

**Signal Values:**

```
LONG SPOT / SHORT FUT    → Cash & Carry trade available
SHORT SPOT / LONG FUT    → Reverse Cash & Carry available
WATCH                    → Developing, below threshold
NO TRADE                 → Filtered out
```

**Top Opportunities Panel:**

```
════════════════════════════════════════════
  🏆 TOP SETUP
════════════════════════════════════════════
  BTC — Binance
  ─────────────────────────────────────────
  Spot:           64,000.00 USDT
  Futures:        64,420.00 USDT  (Dec 27)
  DTE:            42 days
  ─────────────────────────────────────────
  Basis:          +420.00  (+0.66%)
  Annualized:     +13.8%
  Net Edge:       +10.9% (after fees)
  ─────────────────────────────────────────
  Volume (24h):   $2.4B
  Spread:         0.02%
  ─────────────────────────────────────────
  Signal:    BUY SPOT / SELL FUT
  Score:     84 / 100
════════════════════════════════════════════
```

**Dashboard Sections:**
1. **Header bar** — System status, last update time, active feeds count
2. **Summary metrics** — Total opportunities scanned, active signals, top score
3. **Top Opportunities** — Top 3 setups in card format
4. **Full Scanner Table** — All opportunities, sortable by score
5. **Basis History Chart** — Optional: time series of basis for selected pair
6. **Feed Status** — Connection status per exchange per instrument

---

### 8. Storage

**Purpose:** Persist all basis observations for future analysis, backtesting, and signal research.

**Primary Storage:** SQLite (V1) — simple, zero-ops, sufficient for V1 data volumes. Can be migrated to PostgreSQL or DuckDB for V2+.

**Schema:**

```sql
-- schema.sql

CREATE TABLE basis_observations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               DATETIME NOT NULL,
    exchange                TEXT NOT NULL,
    asset                   TEXT NOT NULL,
    spot_symbol             TEXT NOT NULL,
    futures_symbol          TEXT NOT NULL,
    contract_type           TEXT NOT NULL,       -- DATED | PERPETUAL
    expiry_date             DATE,
    days_to_expiry          REAL,
    spot_bid                REAL NOT NULL,
    spot_ask                REAL NOT NULL,
    spot_mid                REAL NOT NULL,
    futures_bid             REAL NOT NULL,
    futures_ask             REAL NOT NULL,
    futures_mid             REAL NOT NULL,
    basis_abs               REAL NOT NULL,
    basis_pct               REAL NOT NULL,
    annualized_basis        REAL,
    net_edge_cc_pct         REAL,
    annualized_net_edge_cc  REAL,
    signal                  TEXT NOT NULL,
    score                   REAL NOT NULL,
    volume_usd_24h          REAL,
    spread_pct              REAL
);

CREATE INDEX idx_basis_obs_timestamp   ON basis_observations(timestamp);
CREATE INDEX idx_basis_obs_exchange    ON basis_observations(exchange, asset);
CREATE INDEX idx_basis_obs_expiry      ON basis_observations(expiry_date);

CREATE TABLE feed_health_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME NOT NULL,
    exchange        TEXT NOT NULL,
    event_type      TEXT NOT NULL,   -- CONNECT | DISCONNECT | RECONNECT | ERROR | STALE
    details         TEXT
);
```

**Write Frequency:** Every N seconds per pair (default: every 60s or on significant basis change > 5bps).

**Parquet Export:** Optional weekly export for external analysis:
```
storage/exports/basis_YYYYMMDD.parquet
```

---

### 9. Config

**default.yaml:**

```yaml
system:
  scan_interval_seconds: 5
  log_level: INFO
  storage_path: ./data/arbitrage.db

exchanges:
  binance:
    enabled: true
    fee_taker: 0.0004
    reliability_score: 95
  bybit:
    enabled: true
    fee_taker: 0.0006
    reliability_score: 90
  okx:
    enabled: true
    fee_taker: 0.0005
    reliability_score: 88

assets:
  - symbol: BTC/USDT
    min_volume_usd_24h: 10_000_000
  - symbol: ETH/USDT
    min_volume_usd_24h: 5_000_000
  - symbol: SOL/USDT
    min_volume_usd_24h: 1_000_000
  - symbol: BNB/USDT
    min_volume_usd_24h: 1_000_000

filters:
  min_annualized_basis: 0.05
  max_spread_pct: 0.001
  max_staleness_seconds: 5
  slippage_assumption: 0.0003

scoring:
  weights:
    edge: 0.35
    liquidity: 0.25
    spread: 0.20
    freshness: 0.10
    exchange: 0.10

storage:
  write_interval_seconds: 60
  basis_change_threshold_bps: 5
  export_parquet: true
  export_interval_days: 7

dashboard:
  refresh_interval_seconds: 3
  top_opportunities_count: 3
  min_score_to_display: 0
```

---

## Data Schema

### InstrumentQuote (Normalized)

```python
class ContractType(str, Enum):
    SPOT = "SPOT"
    DATED_FUTURE = "DATED_FUTURE"
    PERPETUAL = "PERPETUAL"

class InstrumentQuote(BaseModel):
    # Identity
    exchange: str                          # "binance" | "bybit" | "okx"
    raw_symbol: str                        # Exchange-native symbol
    internal_symbol: str                   # Internal normalized symbol
    asset: str                             # "BTC" | "ETH" | ...
    quote_currency: str                    # "USDT"
    contract_type: ContractType
    expiry: Optional[date] = None          # None for SPOT and PERP

    # Pricing
    bid: float
    ask: float
    mid: float                             # (bid + ask) / 2
    last: float

    # Market info
    volume_24h: Optional[float] = None     # In quote currency (USD)
    open_interest: Optional[float] = None  # In base asset
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None

    # Metadata
    exchange_timestamp: datetime           # Exchange-reported time
    ingest_timestamp: datetime             # When we received it
    is_stale: bool = False
    is_dead: bool = False

    @property
    def spread_pct(self) -> float:
        return (self.ask - self.bid) / self.mid if self.mid > 0 else float('inf')

    @property
    def days_to_expiry(self) -> Optional[float]:
        if self.expiry is None:
            return None
        delta = self.expiry - date.today()
        return max(delta.days, 0.001)  # Avoid division by zero
```

### SpotFuturesPair

```python
class SpotFuturesPair(BaseModel):
    exchange: str
    asset: str
    spot: InstrumentQuote
    futures: InstrumentQuote
    pair_id: str                           # e.g. "binance_BTC_20241227"
    created_at: datetime
```

### Opportunity

```python
class Signal(str, Enum):
    CASH_AND_CARRY = "LONG SPOT / SHORT FUT"
    REVERSE_CC = "SHORT SPOT / LONG FUT"
    WATCH = "WATCH"
    NO_TRADE = "NO TRADE"

class Opportunity(BaseModel):
    pair: SpotFuturesPair
    basis_result: BasisResult
    score: float
    signal: Signal
    passed_filters: bool
    filter_reasons: List[str]
    ranked_at: datetime
```

---

## Basis Calculation Logic

### Step-by-Step

```
1. Fetch spot quote for asset/exchange
2. Fetch futures quote(s) for asset/exchange
3. Validate both quotes are FRESH (not stale/dead)
4. Compute basis metrics (mid-based)
5. Compute executable basis (bid/ask aware)
6. Compute cost-adjusted net edge
7. Annualize all carry metrics
```

### Formulas

```
# Mid-based
basis_abs       = futures_mid - spot_mid
basis_pct       = basis_abs / spot_mid
annualized      = basis_pct × (365 / days_to_expiry)    [dated only]

# Executable — Cash & Carry
exec_cc         = futures_bid - spot_ask                 [I sell futures, buy spot]
exec_cc_pct     = exec_cc / spot_ask
gross_edge_cc   = exec_cc_pct

# Executable — Reverse Cash & Carry
exec_rcc        = spot_bid - futures_ask                 [I sell spot, buy futures]
exec_rcc_pct    = exec_rcc / spot_bid
gross_edge_rcc  = exec_rcc_pct

# Net Edge (after costs)
total_cost      = (2 × fee_rate) + (2 × slippage)
net_edge_cc     = gross_edge_cc - total_cost
net_edge_rcc    = gross_edge_rcc - total_cost

# Annualized Net Edge
ann_net_edge_cc = net_edge_cc × (365 / days_to_expiry)  [dated only]
```

### Perpetual Handling

Perpetual futures **do not have a fixed expiry** — their "carry" is the funding rate, not dated basis. The scanner:
- Displays perpetual basis separately
- Labels it `PERP BASIS` not `CARRY`
- Does not annualize by days-to-expiry
- Flags it as `PERPETUAL` in all outputs

---

## Opportunity Detection Rules

An opportunity is **flagged** only when ALL of the following are true:

```
✓ annualized_basis         > min_annualized_basis (e.g. 5%)
✓ net_edge_after_fees      > 0
✓ volume_24h               > min_volume_usd (e.g. $1M)
✓ spread_pct               < max_spread_pct (e.g. 0.1%)
✓ quote_staleness          < max_staleness_seconds (e.g. 5s)
✓ days_to_expiry           > 1  (avoid expiry day risk)
```

### Signal Classification

```
if futures_mid > spot_mid AND net_edge_cc > 0 AND passes filters:
    → LONG SPOT / SHORT FUT  (Cash & Carry)

if futures_mid < spot_mid AND net_edge_rcc > 0 AND passes filters:
    → SHORT SPOT / LONG FUT  (Reverse Cash & Carry)

if basis exists but below threshold OR edge marginal:
    → WATCH

else:
    → NO TRADE
```

---

## Scoring Model

### Weighted Formula

```python
score = (
    normalize_edge(ann_net_edge)    × 35  +
    normalize_liquidity(vol_usd)    × 25  +
    normalize_spread(spread_pct)    × 20  +
    normalize_freshness(staleness)  × 10  +
    exchange_quality_rating         × 10
)
# Capped at 100
```

### Normalization Functions

```python
def normalize_edge(x: float) -> float:
    # Maps 0%–30% annual edge to 0–1
    return min(max(x / 0.30, 0), 1)

def normalize_liquidity(vol: float) -> float:
    # Log scale: $1M = 0, $1B = 1
    return min(max((log10(vol) - 6) / 3, 0), 1)

def normalize_spread(spread: float) -> float:
    # 0.1% spread = 0, 0% spread = 1
    return min(max(1 - (spread / 0.001), 0), 1)

def normalize_freshness(age_seconds: float) -> float:
    # 0s = 1, 5s = 0
    return min(max(1 - (age_seconds / 5), 0), 1)
```

### Exchange Quality Ratings (Default)

| Exchange | Rating |
|----------|--------|
| Binance | 0.95 |
| Bybit | 0.90 |
| OKX | 0.88 |

---

## Dashboard Specification

### Layout

```
╔══════════════════════════════════════════════════════════════════════╗
║  CRYPTO BASIS SCANNER  v1.0         Last update: 14:32:01 UTC        ║
║  Feeds: BNC✓  BYB✓  OKX✓           Opportunities: 12  |  Signals: 3  ║
╚══════════════════════════════════════════════════════════════════════╝

[ TOP OPPORTUNITIES ]
────────────────────────────────────────────────────────────────────────
  #1 BTC/Binance  Score:84   Ann.Net: +10.9%   LONG SPOT / SHORT FUT
  #2 ETH/OKX      Score:71   Ann.Net: +7.2%    LONG SPOT / SHORT FUT
  #3 SOL/Bybit    Score:58   Ann.Net: +5.1%    WATCH
────────────────────────────────────────────────────────────────────────

[ FULL SCANNER TABLE ]
Symbol  Exchange  Spot        Futures     Expiry    DTE  Basis%  Ann%   Net%   Volume    Spread  Score  Signal
BTC     Binance   64,000.00   64,420.00   Dec-27    42   0.66%   13.8%  10.9%  $2.4B     0.02%   84     LONG SPOT/SHORT FUT
ETH     OKX       3,420.00    3,462.50    Dec-27    42   0.62%   13.0%   7.2%  $800M     0.03%   71     LONG SPOT/SHORT FUT
BTC     Bybit     63,995.00   64,400.00   Dec-27    42   0.63%   13.2%   8.8%  $1.8B     0.02%   79     LONG SPOT/SHORT FUT
SOL     Binance   140.20      141.05      Dec-27    42   0.61%   12.7%   5.1%  $210M     0.05%   58     WATCH
...
```

### Auto-refresh

- Default refresh: every 3 seconds
- Configurable in `config/default.yaml`
- Streamlit `st.rerun()` or `streamlit-autorefresh` component

---

## Storage Layer

### Write Strategy

```python
async def maybe_write(observation: BasisObservation, last_written: Dict):
    time_since_last = now() - last_written.get(observation.pair_id, epoch)
    basis_change    = abs(observation.basis_pct - last_basis.get(observation.pair_id, 0))

    should_write = (
        time_since_last > config.storage.write_interval_seconds
        or basis_change > config.storage.basis_change_threshold_bps / 10000
    )

    if should_write:
        await storage.write(observation)
```

### Query Examples

```sql
-- Basis history for BTC/Binance last 7 days
SELECT timestamp, basis_pct, annualized_basis, score, signal
FROM basis_observations
WHERE exchange = 'binance' AND asset = 'BTC'
  AND timestamp > datetime('now', '-7 days')
ORDER BY timestamp;

-- Best opportunities in last 1 hour
SELECT *
FROM basis_observations
WHERE timestamp > datetime('now', '-1 hour')
  AND signal != 'NO TRADE'
ORDER BY score DESC
LIMIT 20;
```

---

## Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Language | Python 3.11+ | Ecosystem, async support |
| Exchange API | `ccxt` + native clients | Broad coverage + customization |
| Async runtime | `asyncio` + `websockets` | Non-blocking I/O |
| Data models | `pydantic` v2 | Validation + serialization |
| Numerics | `numpy` + `pandas` | Array operations + time series |
| Dashboard | `streamlit` | Rapid professional UI |
| Charts | `plotly` | Interactive time series |
| Storage | `sqlite3` (built-in) | Zero-ops, V1 sufficient |
| Parquet export | `pyarrow` | Efficient columnar storage |
| Logging | `structlog` | Structured, queryable logs |
| Config | `pydantic-settings` + `PyYAML` | Typed, validated config |
| Testing | `pytest` + `pytest-asyncio` | Async test support |

**requirements.txt:**
```
ccxt>=4.0.0
websockets>=12.0
pydantic>=2.0
pydantic-settings>=2.0
numpy>=1.26
pandas>=2.0
streamlit>=1.30
plotly>=5.18
pyarrow>=14.0
structlog>=23.0
PyYAML>=6.0
python-dotenv>=1.0
pytest>=7.4
pytest-asyncio>=0.21
aiohttp>=3.9
```

---

## Reliability Requirements

### Failure Isolation

```
- Each connector runs in its own asyncio task
- A crash in one connector does NOT affect others
- Main analytics loop continues even if a feed is dead
- Dead feeds are marked in dashboard with last-seen timestamp
```

### Reconnect Logic

```python
async def managed_connect(connector: BaseConnector):
    backoff = ExponentialBackoff(base=1, max=60)
    while True:
        try:
            await connector.connect()
            backoff.reset()
            await connector.run()
        except (ConnectionError, WebSocketException) as e:
            wait = backoff.next()
            log.warning(f"{connector.exchange_id} disconnected: {e}. Reconnecting in {wait}s")
            await asyncio.sleep(wait)
```

### Stale Quote Handling

```
Quote age 0–5s    → FRESH  → use normally
Quote age 5–30s   → STALE  → use with warning flag
Quote age >30s    → DEAD   → exclude from opportunities
```

### Logging

All logs use structured JSON format:
```json
{
  "timestamp": "2024-12-15T14:32:01.123Z",
  "level": "WARNING",
  "event": "quote_stale",
  "exchange": "bybit",
  "symbol": "BTC-27DEC24",
  "age_seconds": 12.3,
  "last_price": 64400.0
}
```

---

## Configuration Reference

### Environment Variables (.env)

```bash
# Exchange API keys (read-only, for authenticated endpoints if needed)
BINANCE_API_KEY=
BINANCE_SECRET=
BYBIT_API_KEY=
BYBIT_SECRET=
OKX_API_KEY=
OKX_SECRET=
OKX_PASSPHRASE=

# Storage
DB_PATH=./data/arbitrage.db
LOG_PATH=./logs/scanner.log
LOG_LEVEL=INFO

# Dashboard
DASHBOARD_PORT=8501
DASHBOARD_REFRESH_SECONDS=3
```

### Runtime Overrides

All config values can be overridden at runtime via environment variables using the prefix `ARBS_`:
```bash
ARBS_FILTERS__MIN_ANNUALIZED_BASIS=0.08  # Override min basis to 8%
ARBS_SYSTEM__SCAN_INTERVAL_SECONDS=2     # Faster scan
```

---

## Build Order & Milestones

### Milestone 1 — Data Infrastructure (Days 1–3)

**Goal:** Receive and normalize live market data from all 3 exchanges.

```
[ ] config/settings.py — Pydantic settings model
[ ] normalization/schema.py — InstrumentQuote, SpotFuturesPair models
[ ] normalization/symbol_map.py — Cross-exchange symbol mapping
[ ] connectors/base.py — Abstract connector interface
[ ] connectors/binance.py — Binance WebSocket connector
[ ] connectors/bybit.py — Bybit WebSocket connector
[ ] connectors/okx.py — OKX WebSocket connector
[ ] market_data/store.py — In-memory quote store
[ ] market_data/staleness.py — Quote freshness validation
[ ] utils/logger.py — Structured logging

Acceptance: Print live normalized BTC/USDT spot + futures quotes from all 3 exchanges.
```

### Milestone 2 — Basis Engine (Days 4–5)

**Goal:** Compute all basis metrics for all valid pairs.

```
[ ] market_data/aggregator.py — Spot/futures pair matching
[ ] arbitrage/basis.py — Core basis calculations
[ ] arbitrage/carry.py — Annualized carry
[ ] arbitrage/pairs.py — Pair management
[ ] filters/liquidity.py
[ ] filters/spread.py
[ ] filters/edge.py
[ ] filters/staleness.py

Acceptance: Print BasisResult for all valid pairs every 5 seconds with correct math.
```

### Milestone 3 — Scoring & Ranking (Day 6)

**Goal:** Score and rank all filtered opportunities.

```
[ ] scoring/scorer.py — Composite 0–100 score
[ ] scoring/ranker.py — Sort by score
[ ] Opportunity model with full signal logic

Acceptance: Ranked list of opportunities printed to console with scores and signals.
```

### Milestone 4 — Dashboard (Days 7–8)

**Goal:** Professional scanner UI in Streamlit.

```
[ ] dashboard/formatter.py — Number formatting
[ ] dashboard/scanner_table.py — Main table
[ ] dashboard/top_setups.py — Top 3 cards
[ ] dashboard/app.py — Main Streamlit app

Acceptance: Live dashboard refreshing every 3s showing ranked opportunities.
```

### Milestone 5 — Storage & Logging (Day 9)

**Goal:** Persist basis history.

```
[ ] storage/schema.sql — SQLite schema
[ ] storage/writer.py — Async writer
[ ] storage/reader.py — Query interface
[ ] Parquet export script

Acceptance: SQLite DB populated with basis observations; able to query history.
```

### Milestone 6 — Hardening (Day 10)

**Goal:** Production reliability.

```
[ ] Reconnect logic for all connectors
[ ] Error isolation per connector
[ ] Feed health logging
[ ] Dashboard feed status panel
[ ] Unit tests for basis math, filters, scoring
[ ] Integration test with mock data

Acceptance: System runs 24h without crash; clean reconnects on simulated disconnect.
```

---

## Future Expansion Roadmap

### V2 — Funding Arbitrage + Perpetuals Deep Dive
- Funding rate ingestion and normalization
- Funding-adjusted carry calculations
- Spot vs. Perpetual + funding arb opportunities
- Execution infrastructure (read-only order preview)
- Additional exchanges (Deribit, Kraken, Gate.io)

### V3 — Cross-Exchange Arbitrage
- Same instrument across multiple exchanges
- Transfer time and fee modeling
- Basis convergence detection

### V4 — Statistical Arbitrage
- Basis mean reversion signals
- Z-score based entry/exit triggers
- Rolling basis spread analysis
- Cointegration pairs (ETH/BTC spread, etc.)

### V5 — Options & Volatility
- Options market data ingestion
- Put-call parity checks
- Implied volatility surface
- Vol arbitrage opportunities

### V6 — Execution Layer
- Smart order routing
- Position management
- Risk limits and controls
- Live P&L tracking

---

## Appendix: Example Output

### Console Output (Pre-Dashboard)

```
══════════════════════════════════════════════════════════════════════
 CRYPTO BASIS SCANNER — 2024-12-15 14:32:01 UTC
══════════════════════════════════════════════════════════════════════

Scanning: BTC ETH SOL BNB | Exchanges: Binance Bybit OKX

RANKED OPPORTUNITIES (3 signals found):

Rank  Symbol  Exchange  Spot        Futures     DTE  Ann%   Net%   Score  Signal
#1    BTC     Binance   64,000.00   64,420.00   42   13.8%  10.9%  84     LONG SPOT / SHORT FUT
#2    BTC     Bybit     63,995.00   64,400.00   42   13.2%   8.8%  79     LONG SPOT / SHORT FUT
#3    ETH     OKX        3,420.00    3,462.50   42   13.0%   7.2%  71     LONG SPOT / SHORT FUT

WATCH LIST (below threshold):
      SOL     Binance     140.20      141.05    42   12.7%   5.1%  58     WATCH
      BNB     Bybit       543.10      547.20    42   11.3%   2.8%  41     WATCH

══════════════════════════════════════════════════════════════════════
```

---

*V1 Institutional Crypto Arbitrage Scanner — System Design Document*
*Version: 1.0 | Status: Engineering Reference*
