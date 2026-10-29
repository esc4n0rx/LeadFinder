"""SQLite persistence. Connections belong to a single operation/thread."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from leadfinder.models import Lead


def now():
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, database):
        self.database = str(Path(database).resolve())

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='searches'").fetchone()
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 8:
                raise RuntimeError('Esta base pertence a uma versão mais recente do LeadFinder.')
            if not exists:
                db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
                version = 1
            if version < 2:
                if exists:
                    backup = self.database + '.phase1-backup.sqlite3'
                    if not Path(backup).exists():
                        target = sqlite3.connect(backup)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                from leadfinder.migrations import migrate_v2
                migrate_v2(db)
                version = 2
            if version < 3:
                if exists:
                    backup = self.database + '.phase2-backup.sqlite3'
                    if not Path(backup).exists():
                        target = sqlite3.connect(backup)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                from leadfinder.migrations import migrate_v3
                migrate_v3(db)
            if version < 4:
                if exists:
                    backup = self.database + '.phase3-backup.sqlite3'
                    if not Path(backup).exists():
                        target = sqlite3.connect(backup)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                from leadfinder.migrations import migrate_v4
                migrate_v4(db)
            if version < 5:
                if exists:
                    backup = self.database + '.before-ai-backup.sqlite3'
                    if not Path(backup).exists():
                        target = sqlite3.connect(backup)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                from leadfinder.migrations import migrate_v5
                migrate_v5(db)
            if version < 6:
                if exists:
                    backup = self.database + '.before-categories-backup.sqlite3'
                    if not Path(backup).exists():
                        target = sqlite3.connect(backup)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                from leadfinder.migrations import migrate_v6
                migrate_v6(db)
            if version < 7:
                if exists:
                    backup = self.database + '.before-crm-backup.sqlite3'
                    if not Path(backup).exists():
                        target = sqlite3.connect(backup)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                from leadfinder.migrations import migrate_v7
                migrate_v7(db)
            if version < 8:
                if exists:
                    backup=self.database+'.before-agents-backup.sqlite3'
                    if not Path(backup).exists():
                        target=sqlite3.connect(backup)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                from leadfinder.migrations import migrate_v8
                migrate_v8(db)

    def recover_interrupted(self):
        with self.connection() as db:
            db.execute(
                "UPDATE searches SET status='interrupted', message=?, finished_at=? "
                "WHERE status IN ('queued', 'running')",
                ("A aplicação foi encerrada durante a coleta. Os leads salvos foram preservados.", now()),
            )

    def create_search(self, search_id, term, location, limit, *, workspace_id=1, area=None, require_phone=False, category_id=None):
        with self.connection() as db:
            if category_id is not None and not db.execute('SELECT 1 FROM lead_categories WHERE id=? AND workspace_id=?',(category_id,workspace_id)).fetchone():
                raise ValueError('Categoria não encontrada neste workspace.')
            db.execute(
                "INSERT INTO searches (id,term,location,max_results,created_at,workspace_id,postcode,radius_km,center_lat,center_lon,require_phone,lead_category_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (search_id, term, location, limit, now(), workspace_id,
                 area.postcode if area else None, area.radius_km if area else None,
                 area.latitude if area else None, area.longitude if area else None, int(require_phone),category_id),
            )

    def update_search(self, search_id, **values):
        allowed = {"status", "found", "processed", "saved", "failed", "message", "cancel_requested", "finished_at", "skipped_phone", "skipped_distance", "skipped_coordinates"}
        if not values or not set(values) <= allowed:
            raise ValueError("Campos de busca inválidos")
        with self.connection() as db:
            db.execute(
                f"UPDATE searches SET {', '.join(f'{key}=?' for key in values)} WHERE id=?",
                (*values.values(), search_id),
            )

    def get_search(self, search_id, workspace_id=None):
        with self.connection() as db:
            row = db.execute("SELECT * FROM searches WHERE id=?" + (" AND workspace_id=?" if workspace_id is not None else ""),
                             (search_id, workspace_id) if workspace_id is not None else (search_id,)).fetchone()
            return dict(row) if row else None

    def searches(self, workspace_id):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM searches WHERE workspace_id=? ORDER BY created_at DESC LIMIT 30", (workspace_id,))]

    def save_lead(self, search_id, lead: Lead):
        values = lead.to_dict()
        search = self.get_search(search_id)
        if not search:
            raise ValueError('Busca não encontrada')
        values['workspace_id'] = search['workspace_id']
        values["details"] = json.dumps(values["details"], ensure_ascii=False)
        stamp = now()
        columns = list(values) + ["first_seen_at", "last_seen_at"]
        # Preserve previously collected data when a later visit omits a field.
        updates = ", ".join(
            "details=json_patch(leads.details, excluded.details)" if key == "details"
            else f"{key}=COALESCE(excluded.{key}, leads.{key})"
            for key in values if key not in {"identity", "workspace_id"}
        )
        with self.connection() as db:
            row = db.execute(
                f"INSERT INTO leads ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                f"ON CONFLICT(workspace_id,identity) DO UPDATE SET {updates}, last_seen_at=excluded.last_seen_at RETURNING id",
                (*values.values(), stamp, stamp),
            ).fetchone()
            db.execute("INSERT OR IGNORE INTO search_leads VALUES (?,?)", (search_id, row["id"]))
            db.execute('''INSERT OR IGNORE INTO lead_category_links(workspace_id,lead_id,category_id)
                SELECT workspace_id,?,lead_category_id FROM searches WHERE id=? AND lead_category_id IS NOT NULL''',
                       (row['id'],search_id))

    def list_leads(self, query="", search_id="", page=1, per_page=25, *, workspace_id, only_phone=False, category_id=None, contact_status=None, grouped=False, stage=None, scope_query=""):
        conditions, params = ['leads.workspace_id=?'], [workspace_id]
        if category_id == 0:
            conditions.append('NOT EXISTS (SELECT 1 FROM lead_category_links l WHERE l.lead_id=leads.id AND l.workspace_id=leads.workspace_id)')
        elif category_id is not None:
            conditions.append('EXISTS (SELECT 1 FROM lead_category_links l WHERE l.lead_id=leads.id AND l.category_id=? AND l.workspace_id=leads.workspace_id)')
            params.append(category_id)
        status_sql="COALESCE((SELECT status FROM lead_contacts WHERE lead_id=leads.id AND workspace_id=leads.workspace_id),'new')"
        if contact_status:
            conditions.append(status_sql+'=?')
            params.append(contact_status)
        if stage:
            conditions.append("COALESCE((SELECT stage FROM lead_profiles WHERE lead_id=leads.id AND workspace_id=leads.workspace_id),'new')=?")
            params.append(stage)
        if only_phone:
            conditions.append("NULLIF(TRIM(phone),'') IS NOT NULL")
        for query in (query,scope_query):
            if not query:continue
            conditions.append("(name LIKE ? ESCAPE '\\' OR address LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\')")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.extend([f"%{escaped}%"] * 4)
        if search_id:
            conditions.append("id IN (SELECT lead_id FROM search_leads WHERE search_id=?)")
            params.append(search_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.connection() as db:
            total = db.execute("SELECT COUNT(*) FROM leads" + where, params).fetchone()[0]
            order = "(SELECT MIN(c.name COLLATE NOCASE) FROM lead_category_links l JOIN lead_categories c ON c.id=l.category_id WHERE l.lead_id=leads.id AND l.workspace_id=leads.workspace_id) IS NULL, (SELECT MIN(c.name COLLATE NOCASE) FROM lead_category_links l JOIN lead_categories c ON c.id=l.category_id WHERE l.lead_id=leads.id AND l.workspace_id=leads.workspace_id) COLLATE NOCASE, " if grouped else ''
            rows = db.execute(
                "SELECT leads.*, "+status_sql+" AS contact_status FROM leads" + where + " ORDER BY "+order+"last_seen_at DESC, id DESC LIMIT ? OFFSET ?",
                (*params, per_page, (page - 1) * per_page),
            )
            from leadfinder.lead_directory import enrich_leads
            return {"items": enrich_leads(db,[self._lead(row) for row in rows],workspace_id), "total": total, "page": page, "per_page": per_page}

    def get_lead(self, lead_id, workspace_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM leads WHERE id=? AND workspace_id=?", (lead_id, workspace_id)).fetchone()
            if not row:
                return None
            result = self._lead(row)
            contact=db.execute('SELECT status FROM lead_contacts WHERE lead_id=? AND workspace_id=?',(lead_id,workspace_id)).fetchone()
            result['contact_status']=contact['status'] if contact else 'new'
            from leadfinder.lead_directory import enrich_leads
            enrich_leads(db,[result],workspace_id)
            result["searches"] = [dict(item) for item in db.execute(
                "SELECT s.id,s.term,s.location,s.postcode,s.radius_km FROM searches s JOIN search_leads sl ON sl.search_id=s.id WHERE sl.lead_id=? AND s.workspace_id=? ORDER BY s.created_at DESC",
                (lead_id, workspace_id),
            )]
            return result

    def stats(self, workspace_id):
        with self.connection() as db:
            row = db.execute(
                "SELECT COUNT(*) total, COUNT(NULLIF(phone,'')) with_phone, COUNT(NULLIF(website,'')) with_website FROM leads WHERE workspace_id=?", (workspace_id,)
            ).fetchone()
            return dict(row)

    @staticmethod
    def _lead(row):
        result = dict(row)
        result["details"] = json.loads(result["details"])
        return result
