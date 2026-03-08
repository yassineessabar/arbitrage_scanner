-- ═══════════════════════════════════════════════════════════
-- V1 Institutional Crypto Arbitrage Scanner — SQLite Schema
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS basis_observations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               DATETIME NOT NULL,
    exchange                TEXT NOT NULL,
    asset                   TEXT NOT NULL,
    spot_symbol             TEXT NOT NULL,
    futures_symbol          TEXT NOT NULL,
    contract_type           TEXT NOT NULL,       -- DATED_FUTURE | PERPETUAL
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

CREATE INDEX IF NOT EXISTS idx_basis_obs_timestamp
    ON basis_observations(timestamp);
CREATE INDEX IF NOT EXISTS idx_basis_obs_exchange
    ON basis_observations(exchange, asset);
CREATE INDEX IF NOT EXISTS idx_basis_obs_expiry
    ON basis_observations(expiry_date);

CREATE TABLE IF NOT EXISTS feed_health_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME NOT NULL,
    exchange        TEXT NOT NULL,
    event_type      TEXT NOT NULL,   -- CONNECT | DISCONNECT | RECONNECT | ERROR | STALE
    details         TEXT
);

CREATE INDEX IF NOT EXISTS idx_feed_health_timestamp
    ON feed_health_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_feed_health_exchange
    ON feed_health_log(exchange);
