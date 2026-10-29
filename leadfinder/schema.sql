PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS searches (
    id TEXT PRIMARY KEY,
    term TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    max_results INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    found INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    saved INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT 'Preparando navegador…',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT,
    phone TEXT,
    address TEXT,
    website TEXT,
    rating REAL,
    review_count INTEGER,
    hours TEXT,
    plus_code TEXT,
    latitude REAL,
    longitude REAL,
    maps_url TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_leads (
    search_id TEXT NOT NULL REFERENCES searches(id),
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    PRIMARY KEY (search_id, lead_id)
);
CREATE INDEX IF NOT EXISTS idx_leads_seen ON leads(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_leads_lead ON search_leads(lead_id);
PRAGMA user_version = 1;
