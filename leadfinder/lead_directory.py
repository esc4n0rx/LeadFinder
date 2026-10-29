"""Workspace-owned organization and contact state, independent of Maps metadata."""
import sqlite3

from leadfinder.repository import now
from leadfinder.outreach import normalize_phone


class DirectoryError(ValueError):
    pass


def phone_key(value):
    try:
        return normalize_phone(value)
    except ValueError:
        return None


def record_outgoing(db, workspace_id, phone, stamp=None):
    """A real, accepted campaign starts contact, never proves a conversation."""
    normalized = phone_key(phone)
    if not normalized:
        return
    db.create_function('lead_phone',1,phone_key,deterministic=True)
    db.execute('''INSERT INTO lead_contacts(lead_id,workspace_id,status,updated_at)
        SELECT id,workspace_id,'contacted',? FROM leads WHERE workspace_id=? AND lead_phone(phone)=?
        ON CONFLICT(lead_id) DO UPDATE SET
        status=CASE WHEN lead_contacts.status='conversed' THEN 'conversed' ELSE 'contacted' END,
        updated_at=excluded.updated_at''',(stamp or now(),workspace_id,normalized))
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='lead_profiles'").fetchone():
        db.execute('''INSERT INTO lead_profiles SELECT id,workspace_id,'contacted',? FROM leads
            WHERE workspace_id=? AND lead_phone(phone)=? ON CONFLICT(lead_id) DO UPDATE SET
            stage=CASE WHEN lead_profiles.stage='new' THEN 'contacted' ELSE lead_profiles.stage END,
            updated_at=excluded.updated_at''',(stamp or now(),workspace_id,normalized))


class LeadDirectory:
    def __init__(self, repository):
        self.repo = repository

    def categories(self, workspace_id):
        with self.repo.connection() as db:
            return [dict(row) for row in db.execute('''SELECT c.id,c.name,COUNT(l.lead_id) AS lead_count
                FROM lead_categories c LEFT JOIN lead_category_links l
                ON l.category_id=c.id AND l.workspace_id=c.workspace_id
                WHERE c.workspace_id=? GROUP BY c.id ORDER BY c.name COLLATE NOCASE,c.id''',(workspace_id,))]

    def save_category(self, workspace_id, name, category_id=None):
        if not isinstance(name,str) or not 2 <= len(name.strip()) <= 60:
            raise DirectoryError('O nome da categoria deve ter entre 2 e 60 caracteres.')
        try:
            with self.repo.connection() as db:
                if category_id is None:
                    if db.execute('SELECT COUNT(*) FROM lead_categories WHERE workspace_id=?',(workspace_id,)).fetchone()[0]>=100:
                        raise DirectoryError('O workspace pode ter até 100 categorias.')
                    return db.execute('INSERT INTO lead_categories(workspace_id,name,created_at) VALUES(?,?,?)',
                                      (workspace_id,name.strip(),now())).lastrowid
                changed=db.execute('UPDATE lead_categories SET name=? WHERE id=? AND workspace_id=?',
                                   (name.strip(),category_id,workspace_id)).rowcount
                if not changed:
                    raise LookupError('Categoria não encontrada.')
                return category_id
        except sqlite3.IntegrityError as error:
            raise DirectoryError('Já existe uma categoria com esse nome.') from error

    def delete_category(self, workspace_id, category_id):
        with self.repo.connection() as db:
            if not db.execute('DELETE FROM lead_categories WHERE id=? AND workspace_id=?',(category_id,workspace_id)).rowcount:
                raise LookupError('Categoria não encontrada.')

    def update_lead(self, workspace_id, lead_id, data):
        if not isinstance(data,dict) or not data or not set(data)<= {'category_ids','contact_status'}:
            raise DirectoryError('Informe as categorias ou o status de contato.')
        ids=data.get('category_ids')
        if 'category_ids' in data and (not isinstance(ids,list) or len(ids)>100 or
                any(type(item) is not int or item<1 for item in ids) or len(set(ids))!=len(ids)):
            raise DirectoryError('Selecione categorias válidas, sem repetições.')
        if 'contact_status' in data and data['contact_status'] not in ('new','contacted','conversed'):
            raise DirectoryError('Status de contato inválido.')
        with self.repo.connection() as db:
            if not db.execute('SELECT 1 FROM leads WHERE id=? AND workspace_id=?',(lead_id,workspace_id)).fetchone():
                raise LookupError('Lead não encontrado.')
            if ids is not None:
                available={row[0] for row in db.execute('SELECT id FROM lead_categories WHERE workspace_id=?',(workspace_id,))}
                if not set(ids)<=available:
                    raise DirectoryError('Uma categoria não pertence a este workspace.')
                db.execute('DELETE FROM lead_category_links WHERE lead_id=? AND workspace_id=?',(lead_id,workspace_id))
                db.executemany('INSERT INTO lead_category_links(workspace_id,lead_id,category_id) VALUES(?,?,?)',
                               [(workspace_id,lead_id,item) for item in ids])
            if 'contact_status' in data:
                db.execute('''INSERT INTO lead_contacts(lead_id,workspace_id,status,updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(lead_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at''',
                           (lead_id,workspace_id,data['contact_status'],now()))
            from leadfinder.crm import lead_event
            lead_event(db,workspace_id,lead_id,'organization','Categorias e/ou status de contato atualizados.')


def enrich_leads(db, leads, workspace_id):
    if not leads:
        return leads
    by_id={lead['id']:lead for lead in leads}
    placeholders=','.join('?' for _ in by_id)
    for lead in leads:
        lead['categories']=[]
        lead.setdefault('contact_status','new')
        lead['stage']='new'
        lead['next_action']=None
    for row in db.execute(f'SELECT lead_id,stage FROM lead_profiles WHERE workspace_id=? AND lead_id IN ({placeholders})',(workspace_id,*by_id)):
        by_id[row['lead_id']]['stage']=row['stage']
    for row in db.execute(f'''SELECT lead_id,MIN(due_at) AS due FROM reminders WHERE workspace_id=?
        AND completed_at IS NULL AND lead_id IN ({placeholders}) GROUP BY lead_id''',(workspace_id,*by_id)):
        by_id[row['lead_id']]['next_action']=row['due']
    for row in db.execute(f'''SELECT l.lead_id,c.id,c.name FROM lead_category_links l
        JOIN lead_categories c ON c.id=l.category_id AND c.workspace_id=l.workspace_id
        WHERE l.workspace_id=? AND l.lead_id IN ({placeholders}) ORDER BY c.name COLLATE NOCASE,c.id''',
        (workspace_id,*by_id)):
        by_id[row['lead_id']]['categories'].append({'id':row['id'],'name':row['name']})
    return leads
