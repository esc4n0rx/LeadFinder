"""Transactional phase 1 → phase 2 migration; preserves IDs and search history."""

SQL_V2 = """
CREATE TABLE users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL,
 username_key TEXT NOT NULL UNIQUE, email TEXT NOT NULL, email_key TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE workspaces (
 id INTEGER PRIMARY KEY, owner_id INTEGER UNIQUE REFERENCES users(id),
 name TEXT NOT NULL, created_at TEXT NOT NULL
);
INSERT INTO workspaces VALUES (1,NULL,'Workspace importado',strftime('%Y-%m-%dT%H:%M:%SZ','now'));
CREATE TABLE auth_sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at REAL NOT NULL
);
CREATE INDEX idx_auth_expiry ON auth_sessions(expires_at);
CREATE TABLE login_attempts (key TEXT PRIMARY KEY, failures INTEGER NOT NULL, expires_at REAL NOT NULL);
ALTER TABLE searches ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1 REFERENCES workspaces(id);
ALTER TABLE searches ADD COLUMN postcode TEXT;
ALTER TABLE searches ADD COLUMN radius_km REAL;
ALTER TABLE searches ADD COLUMN center_lat REAL;
ALTER TABLE searches ADD COLUMN center_lon REAL;
ALTER TABLE searches ADD COLUMN require_phone INTEGER NOT NULL DEFAULT 0;
ALTER TABLE searches ADD COLUMN skipped_phone INTEGER NOT NULL DEFAULT 0;
ALTER TABLE searches ADD COLUMN skipped_distance INTEGER NOT NULL DEFAULT 0;
ALTER TABLE searches ADD COLUMN skipped_coordinates INTEGER NOT NULL DEFAULT 0;
CREATE TABLE leads_v2 (
 id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
 identity TEXT NOT NULL, name TEXT NOT NULL, category TEXT, phone TEXT, address TEXT,
 website TEXT, rating REAL, review_count INTEGER, hours TEXT, plus_code TEXT,
 latitude REAL, longitude REAL, maps_url TEXT NOT NULL, details TEXT NOT NULL DEFAULT '{}',
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, UNIQUE(workspace_id,identity)
);
INSERT INTO leads_v2 SELECT id,1,identity,name,category,phone,address,website,rating,review_count,
 hours,plus_code,latitude,longitude,maps_url,details,first_seen_at,last_seen_at FROM leads;
CREATE TABLE search_leads_v2 (
 search_id TEXT NOT NULL REFERENCES searches(id), lead_id INTEGER NOT NULL REFERENCES leads(id),
 PRIMARY KEY(search_id,lead_id)
);
INSERT INTO search_leads_v2 SELECT * FROM search_leads;
DROP TABLE search_leads;
DROP TABLE leads;
ALTER TABLE leads_v2 RENAME TO leads;
ALTER TABLE search_leads_v2 RENAME TO search_leads;
CREATE INDEX idx_leads_seen ON leads(workspace_id,last_seen_at DESC);
CREATE INDEX idx_searches_workspace ON searches(workspace_id,created_at DESC);
CREATE INDEX idx_search_leads_lead ON search_leads(lead_id);
PRAGMA user_version = 2;
"""


def migrate_v2(db):
    db.execute('PRAGMA foreign_keys = OFF')
    try:
        db.execute('BEGIN IMMEDIATE')
        for statement in SQL_V2.split(';'):
            if statement.strip():
                db.execute(statement)
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('A migração encontrou vínculos inválidos. A base original foi preservada.')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute('PRAGMA foreign_keys = ON')


SQL_V3 = """
CREATE TABLE whatsapp_integrations (
 workspace_id INTEGER PRIMARY KEY REFERENCES workspaces(id), name TEXT NOT NULL, phone TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE message_templates (
 id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL,
 body TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX idx_templates_workspace ON message_templates(workspace_id,archived);
CREATE TABLE campaigns (
 id TEXT PRIMARY KEY, workspace_id INTEGER NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL,
 simulated INTEGER NOT NULL, sender_phone TEXT NOT NULL, interval_seconds INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft', cancel_requested INTEGER NOT NULL DEFAULT 0,
 target_count INTEGER NOT NULL, message_count INTEGER NOT NULL,
 created_at TEXT NOT NULL, finished_at TEXT, error TEXT
);
CREATE UNIQUE INDEX idx_one_running_campaign ON campaigns(workspace_id) WHERE status='running';
CREATE TABLE campaign_messages (
 id INTEGER PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
 target_key TEXT NOT NULL, target_name TEXT NOT NULL, phone TEXT,
 message_index INTEGER NOT NULL, template_name TEXT NOT NULL, body TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', provider_id TEXT, error TEXT, sent_at TEXT,
 UNIQUE(campaign_id,target_key,message_index)
);
CREATE INDEX idx_campaign_workspace ON campaigns(workspace_id,created_at DESC);
CREATE INDEX idx_campaign_messages ON campaign_messages(campaign_id,status,id);
PRAGMA user_version = 3;
"""


def migrate_v3(db):
    try:
        db.execute('BEGIN IMMEDIATE')
        for statement in SQL_V3.split(';'):
            if statement.strip():
                db.execute(statement)
        db.commit()
    except Exception:
        db.rollback()
        raise


def migrate_v4(db):
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute("""CREATE TABLE outreach_events (
            id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            campaign_id TEXT REFERENCES campaigns(id), level TEXT NOT NULL,
            message TEXT NOT NULL, created_at TEXT NOT NULL)""")
        db.execute('CREATE INDEX idx_outreach_events ON outreach_events(workspace_id,campaign_id,id)')
        db.execute('PRAGMA user_version = 4')
        db.commit()
    except Exception:
        db.rollback()
        raise


def migrate_v5(db):
    statements = [
        '''CREATE TABLE ai_integrations (
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id), provider TEXT NOT NULL,
            encrypted_key TEXT NOT NULL, key_hint TEXT NOT NULL, model TEXT NOT NULL,
            provider_workspace TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id,provider))''',
        '''CREATE TABLE ai_threads (
            id TEXT PRIMARY KEY, workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
        '''CREATE TABLE ai_turns (
            id INTEGER PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES ai_threads(id),
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id), request_key TEXT NOT NULL,
            provider TEXT NOT NULL, model TEXT NOT NULL, user_text TEXT NOT NULL,
            reply TEXT, suggestions TEXT NOT NULL DEFAULT '[]', usage TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending', error TEXT, created_at TEXT NOT NULL,
            UNIQUE(workspace_id,request_key))''',
        'CREATE INDEX idx_ai_threads ON ai_threads(workspace_id,updated_at DESC)',
        "CREATE UNIQUE INDEX idx_ai_pending ON ai_turns(workspace_id) WHERE status='pending'",
        'PRAGMA user_version = 5',
    ]
    try:
        db.execute('BEGIN IMMEDIATE')
        for statement in statements:
            db.execute(statement)
        db.commit()
    except Exception:
        db.rollback()
        raise


def migrate_v6(db):
    """Workspace categories and explicit contact tracking; preserve Maps fields."""
    from leadfinder.lead_directory import record_outgoing
    statements = [
        '''CREATE TABLE lead_categories (
            id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            name TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(workspace_id,name COLLATE NOCASE), UNIQUE(workspace_id,id))''',
        'CREATE UNIQUE INDEX idx_lead_workspace_id ON leads(workspace_id,id)',
        '''CREATE TABLE lead_category_links (
            workspace_id INTEGER NOT NULL, lead_id INTEGER NOT NULL, category_id INTEGER NOT NULL,
            PRIMARY KEY(lead_id,category_id),
            FOREIGN KEY(workspace_id,lead_id) REFERENCES leads(workspace_id,id) ON DELETE CASCADE,
            FOREIGN KEY(workspace_id,category_id) REFERENCES lead_categories(workspace_id,id) ON DELETE CASCADE)''',
        'CREATE INDEX idx_category_leads ON lead_category_links(workspace_id,category_id,lead_id)',
        '''CREATE TABLE lead_contacts (
            lead_id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('new','contacted','conversed')),
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id,lead_id) REFERENCES leads(workspace_id,id) ON DELETE CASCADE)''',
        'ALTER TABLE searches ADD COLUMN lead_category_id INTEGER REFERENCES lead_categories(id) ON DELETE SET NULL',
    ]
    try:
        db.execute('BEGIN IMMEDIATE')
        for statement in statements:
            db.execute(statement)
        for row in db.execute("""SELECT c.workspace_id,m.phone,MAX(m.sent_at) AS stamp
            FROM campaign_messages m JOIN campaigns c ON c.id=m.campaign_id
            WHERE m.status='sent' AND c.simulated=0 AND m.target_key!='fictional'
            GROUP BY c.workspace_id,m.phone""").fetchall():
            record_outgoing(db,row['workspace_id'],row['phone'],row['stamp'])
        db.execute('PRAGMA user_version = 6')
        db.commit()
    except Exception:
        db.rollback()
        raise


def migrate_v7(db):
    statements=[
        '''CREATE TABLE lead_profiles (
            lead_id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL,
            stage TEXT NOT NULL DEFAULT 'new' CHECK(stage IN ('new','contacted','replied','demo','customer','lost')),
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id,lead_id) REFERENCES leads(workspace_id,id) ON DELETE CASCADE)''',
        '''CREATE TABLE lead_notes (
            id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL, lead_id INTEGER NOT NULL,
            body TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id,lead_id) REFERENCES leads(workspace_id,id) ON DELETE CASCADE)''',
        '''CREATE TABLE lead_events (
            id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL, lead_id INTEGER NOT NULL,
            kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id,lead_id) REFERENCES leads(workspace_id,id) ON DELETE CASCADE)''',
        'CREATE INDEX idx_lead_events ON lead_events(workspace_id,lead_id,id)',
        '''CREATE TABLE reminders (
            id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL, lead_id INTEGER NOT NULL,
            title TEXT NOT NULL, due_at TEXT NOT NULL, completed_at TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id,lead_id) REFERENCES leads(workspace_id,id) ON DELETE CASCADE)''',
        'CREATE INDEX idx_reminders_due ON reminders(workspace_id,completed_at,due_at)',
        '''CREATE TABLE product_context (
            workspace_id INTEGER PRIMARY KEY REFERENCES workspaces(id),
            data TEXT NOT NULL, updated_at TEXT NOT NULL)''',
        'ALTER TABLE ai_turns ADD COLUMN context_snapshot TEXT',
        'ALTER TABLE campaigns ADD COLUMN scheduled_at TEXT',
        'ALTER TABLE campaigns ADD COLUMN next_send_at TEXT',
        'ALTER TABLE campaigns ADD COLUMN pause_requested INTEGER NOT NULL DEFAULT 0',
        '''CREATE TABLE campaign_jobs (
            campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id) ON DELETE CASCADE,
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id), available_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('queued','running','done')), updated_at TEXT NOT NULL)''',
        'CREATE INDEX idx_campaign_jobs_due ON campaign_jobs(status,available_at)',
        "INSERT INTO lead_profiles SELECT lead_id,workspace_id,CASE WHEN status='new' THEN 'new' WHEN status='conversed' THEN 'replied' ELSE 'contacted' END,updated_at FROM lead_contacts",
        'PRAGMA user_version = 7',
    ]
    try:
        db.execute('BEGIN IMMEDIATE')
        for statement in statements:
            db.execute(statement)
        db.commit()
    except Exception:
        db.rollback()
        raise


def migrate_v8(db):
    statements=[
        '''CREATE TABLE lead_funnels (
            id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            name TEXT NOT NULL, filters TEXT NOT NULL, created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
            UNIQUE(workspace_id,name COLLATE NOCASE))''',
        '''CREATE TABLE ai_tool_calls (
            id TEXT PRIMARY KEY,workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            thread_id TEXT NOT NULL REFERENCES ai_threads(id) ON DELETE CASCADE,
            turn_id INTEGER NOT NULL REFERENCES ai_turns(id) ON DELETE CASCADE,
            tool TEXT NOT NULL,arguments TEXT NOT NULL,signature TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','executing','completed','failed','cancelled','interrupted')),
            result TEXT,preview TEXT,created_at TEXT NOT NULL,finished_at TEXT,
            UNIQUE(turn_id,signature))''',
        'CREATE INDEX idx_agent_actions ON ai_tool_calls(workspace_id,thread_id,turn_id)',
        'PRAGMA user_version = 8',
    ]
    try:
        db.execute('BEGIN IMMEDIATE')
        for statement in statements:
            db.execute(statement)
        db.commit()
    except Exception:
        db.rollback()
        raise
