PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    balance REAL NOT NULL DEFAULT 1000,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    closes_at TEXT NOT NULL,
    resolution_source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
    outcome INTEGER CHECK(outcome IN (0,1)),
    q_yes REAL NOT NULL DEFAULT 0,
    q_no REAL NOT NULL DEFAULT 0,
    liquidity REAL NOT NULL DEFAULT 300,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    market_id INTEGER NOT NULL REFERENCES markets(id),
    probability REAL NOT NULL CHECK(probability >= 0.01 AND probability <= 0.99),
    rationale TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, market_id)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    market_id INTEGER NOT NULL REFERENCES markets(id),
    side TEXT NOT NULL CHECK(side IN ('YES','NO')),
    shares REAL NOT NULL CHECK(shares > 0),
    cost REAL NOT NULL CHECK(cost >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

