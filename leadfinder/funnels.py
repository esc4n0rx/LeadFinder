"""Named views of the sales funnel; existing stages remain stable."""
import json
import sqlite3
from leadfinder.crm import STAGES
from leadfinder.lead_directory import DirectoryError
from leadfinder.repository import now


class FunnelStore:
    def __init__(self,repo):
        self.repo=repo

    def list(self,workspace_id):
        with self.repo.connection() as db:
            return [{**dict(row),'filters':json.loads(row['filters'])} for row in db.execute('SELECT * FROM lead_funnels WHERE workspace_id=? ORDER BY name COLLATE NOCASE,id',(workspace_id,))]

    def get(self,workspace_id,identity):
        return next((row for row in self.list(workspace_id) if row['id']==identity),None)

    def create(self,workspace_id,name,filters):
        if not isinstance(name,str) or not 2<=len(name.strip())<=80:
            raise DirectoryError('O nome do funil deve ter entre 2 e 80 caracteres.')
        if not isinstance(filters,dict) or not set(filters)<={'q','category_id','contact_status','only_phone'}:
            raise DirectoryError('Filtros de funil inválidos.')
        category=filters.get('category_id')
        if category is not None and (type(category) is not int or category<0):
            raise DirectoryError('Categoria inválida.')
        if not isinstance(filters.get('q',''),str) or len(filters.get('q',''))>200 or filters.get('contact_status') not in (None,'','new','contacted','conversed') or type(filters.get('only_phone',False)) is not bool:
            raise DirectoryError('Filtros de funil inválidos.')
        try:
            with self.repo.connection() as db:
                if category and not db.execute('SELECT 1 FROM lead_categories WHERE workspace_id=? AND id=?',(workspace_id,category)).fetchone():
                    raise DirectoryError('Categoria não encontrada neste workspace.')
                if db.execute('SELECT COUNT(*) FROM lead_funnels WHERE workspace_id=?',(workspace_id,)).fetchone()[0]>=100:
                    raise DirectoryError('O workspace pode ter até 100 funis.')
                identity=db.execute('INSERT INTO lead_funnels(workspace_id,name,filters,created_at,updated_at) VALUES(?,?,?,?,?)',
                                    (workspace_id,name.strip(),json.dumps(filters,ensure_ascii=False),now(),now())).lastrowid
            return self.get(workspace_id,identity)
        except sqlite3.IntegrityError:
            raise DirectoryError('Já existe um funil com esse nome.') from None
