PRAGMA foreign_keys = ON;


-- USERS

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    username TEXT NOT NULL
        UNIQUE COLLATE NOCASE,

    password_hash TEXT NOT NULL,

    balance REAL NOT NULL DEFAULT 1000,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);

-- PERSONAL FORECASTS

CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    user_id INTEGER NOT NULL
        REFERENCES users(id),

    question TEXT NOT NULL,

    probability REAL NOT NULL
        CHECK(probability >= 0.01 AND probability <= 0.99),

    notes TEXT NOT NULL DEFAULT '',

    category TEXT NOT NULL DEFAULT 'General',

    resolves_at TEXT,

    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open', 'resolved')),

    outcome INTEGER
        CHECK(outcome IN (0, 1)),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- TRADING MARKETS

CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    question TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'General',

    closes_at TEXT NOT NULL,

    resolution_source TEXT NOT NULL DEFAULT '',

    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open', 'resolved')),

    outcome INTEGER
        CHECK(outcome IN (0, 1)),

    q_yes REAL NOT NULL DEFAULT 0,
    q_no REAL NOT NULL DEFAULT 0,
    liquidity REAL NOT NULL DEFAULT 300,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- MARKET TRADES

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    user_id INTEGER NOT NULL
        REFERENCES users(id),

    market_id INTEGER NOT NULL
        REFERENCES markets(id),

    side TEXT NOT NULL
        CHECK(side IN ('YES', 'NO')),

    shares REAL NOT NULL
        CHECK(shares > 0),

    cost REAL NOT NULL
        CHECK(cost >= 0),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
