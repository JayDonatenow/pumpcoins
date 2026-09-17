"""SQLite connection + schema for Meme Coin Trader.

Single-file schema, applied idempotently on startup.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "meme_coins.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS coins (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address     TEXT UNIQUE NOT NULL,
    name              TEXT,
    symbol            TEXT,
    description       TEXT,
    creator_wallet    TEXT,
    price             REAL,
    liquidity_sol     REAL,
    volume_24h        REAL,
    holder_count      INTEGER DEFAULT 0,
    market_cap        REAL DEFAULT 0,
    pump_url          TEXT,
    replies_count     INTEGER,
    views             INTEGER,
    discovered_at     TEXT NOT NULL DEFAULT (datetime('now')),
    last_updated      TEXT NOT NULL DEFAULT (datetime('now')),
    marked_scam       INTEGER NOT NULL DEFAULT 0,
    scam_reason       TEXT
);

CREATE INDEX IF NOT EXISTS idx_coins_discovered ON coins(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_coins_address ON coins(token_address);

CREATE TABLE IF NOT EXISTS coin_analysis (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    coin_id                   INTEGER NOT NULL UNIQUE REFERENCES coins(id),
    rug_pull_score            REAL,
    honeypot_score            REAL,
    scam_score                REAL,
    community_score           REAL,
    liquidity_score           REAL,
    overall_risk_score        REAL,
    dev_wallet_percentage     REAL,
    is_liquidity_locked       INTEGER,
    is_mint_renounced         INTEGER,
    has_anti_whale            INTEGER,
    is_contract_verified      INTEGER,
    recommendation            TEXT,
    analysis_notes            TEXT,
    analyzed_at               TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_analysis_overall_risk ON coin_analysis(overall_risk_score);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT UNIQUE NOT NULL,
    password_hash  TEXT NOT NULL,
    name           TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_watchlist (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    coin_id           INTEGER NOT NULL REFERENCES coins(id),
    added_at          TEXT NOT NULL DEFAULT (datetime('now')),
    alert_price       REAL,
    UNIQUE(user_id, coin_id)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user ON user_watchlist(user_id);

CREATE TABLE IF NOT EXISTS user_trades (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    coin_id           INTEGER NOT NULL REFERENCES coins(id),
    action            TEXT NOT NULL,
    amount_sol        REAL,
    price_at_trade    REAL,
    entry_price       REAL,
    exit_price        REAL,
    profit_loss_sol   REAL,
    notes             TEXT,
    tx_signature      TEXT,
    traded_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_user ON user_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_coin ON user_trades(coin_id);

CREATE TABLE IF NOT EXISTS coin_price_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    coin_id           INTEGER NOT NULL REFERENCES coins(id),
    price             REAL NOT NULL,
    market_cap        REAL,
    holder_count      INTEGER,
    recorded_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_price_history_coin_time
ON coin_price_history(coin_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS user_wallets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    wallet_address    TEXT NOT NULL,
    connected_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, wallet_address)
);

CREATE INDEX IF NOT EXISTS idx_user_wallets_user ON user_wallets(user_id);

CREATE TABLE IF NOT EXISTS alert_thresholds (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    coin_id           INTEGER NOT NULL REFERENCES coins(id),
    alert_type        TEXT NOT NULL,
    threshold_value   REAL,
    is_active         INTEGER DEFAULT 1,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, coin_id, alert_type)
);

CREATE INDEX IF NOT EXISTS idx_alerts_user ON alert_thresholds(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_coin ON alert_thresholds(coin_id);

CREATE TABLE IF NOT EXISTS alert_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id          INTEGER NOT NULL REFERENCES alert_thresholds(id),
    triggered_value   REAL,
    triggered_at      TEXT NOT NULL DEFAULT (datetime('now')),
    notified          INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_alert_history_alert ON alert_history(alert_id);

CREATE TABLE IF NOT EXISTS user_preferences (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL UNIQUE REFERENCES users(id),
    email_alerts      INTEGER DEFAULT 1,
    email             TEXT,
    digest_frequency  TEXT DEFAULT 'daily',
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coin_twitter_data (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    coin_id           INTEGER NOT NULL UNIQUE REFERENCES coins(id),
    tweet_count       INTEGER DEFAULT 0,
    total_likes       INTEGER DEFAULT 0,
    total_retweets    INTEGER DEFAULT 0,
    total_replies     INTEGER DEFAULT 0,
    checked_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_twitter_coin ON coin_twitter_data(coin_id);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
