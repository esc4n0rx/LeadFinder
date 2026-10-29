"""Manual catalog corrections and deliberate, workspace-scoped deletion."""
import hashlib
import json
import math
from urllib.parse import urlsplit

from leadfinder.crm import CRM,lead_event,validate_ids
from leadfinder.lead_directory import DirectoryError,phone_key


class LeadConflict(DirectoryError):
    pass


class LeadEditor:
    def __init__(self,repo):
        self.repo=repo

    def update(self,workspace_id,lead_id,data):
        limits={'name':200,'category':120,'phone':40,'address':1000,'website':2000,'hours':4000,'plus_code':120,'description':4000}
        allowed=set(limits)|{'latitude','longitude','rating','review_count'}
        if not isinstance(data,dict) or not data or not set(data)<=allowed:
            raise DirectoryError('Informe os campos do estabelecimento que deseja editar.')
        changes={}
        for key,value in data.items():
            if key in limits:
                if not isinstance(value,str) or len(value.strip())>limits[key] or (key=='name' and len(value.strip())<2):
                    raise DirectoryError('Confira o campo '+key+'.')
                value=value.strip()
                if key=='website' and value:
                    try:
                        url=urlsplit(value)
                        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password:
                            raise ValueError()
                    except ValueError:
                        raise DirectoryError('Informe um site completo com http:// ou https://.') from None
                changes[key]=value or None
            elif key=='review_count':
                if value is not None and (type(value) is not int or not 0<=value<=1000000000):
                    raise DirectoryError('Quantidade de avaliações inválida.')
                changes[key]=value
            else:
                bounds={'latitude':(-90,90),'longitude':(-180,180),'rating':(0,5)}[key]
                if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not bounds[0]<=value<=bounds[1]):
                    raise DirectoryError('Coordenada ou nota inválida.')
                changes[key]=value
        with self.repo.connection() as db:
            CRM(self.repo).require_leads(db,workspace_id,[lead_id])
            if 'description' in changes:
                details=json.loads(db.execute('SELECT details FROM leads WHERE id=? AND workspace_id=?',(lead_id,workspace_id)).fetchone()[0])
                details['description']=changes.pop('description')
                changes['details']=json.dumps(details,ensure_ascii=False)
            db.execute('UPDATE leads SET '+','.join(key+'=?' for key in changes)+' WHERE id=? AND workspace_id=?',(*changes.values(),lead_id,workspace_id))
            # first_seen_at/last_seen_at describe collection, never manual corrections.
            lead_event(db,workspace_id,lead_id,'edit','Dados do estabelecimento editados manualmente.')
        return self.repo.get_lead(lead_id,workspace_id)

    def _preview(self,db,workspace_id,ids):
        validate_ids(ids)
        marks=','.join('?' for _ in ids)
        rows=[dict(row) for row in db.execute(f'''SELECT l.*,
            COALESCE((SELECT MAX(id) FROM lead_events e WHERE e.workspace_id=l.workspace_id AND e.lead_id=l.id),0) AS revision
            FROM leads l WHERE l.workspace_id=? AND l.id IN ({marks}) ORDER BY l.id''',(workspace_id,*ids))]
        if len(rows)!=len(ids):
            raise LookupError('Um lead não foi encontrado neste workspace.')
        db.create_function('lead_phone',1,phone_key,deterministic=True)
        dependent=db.execute(f'''SELECT DISTINCT c.id,c.name FROM campaigns c JOIN campaign_messages m ON m.campaign_id=c.id
            WHERE c.workspace_id=? AND c.status IN ('draft','scheduled','running','paused','interrupted','partial')
            AND m.status IN ('pending','sending','uncertain') AND m.target_key!='fictional'
            AND EXISTS(SELECT 1 FROM leads l WHERE l.workspace_id=c.workspace_id AND l.id IN ({marks}) AND lead_phone(l.phone)=m.phone)
            LIMIT 5''',(workspace_id,*ids)).fetchall()
        if dependent:
            raise LeadConflict('Há tentativas pendentes ou sem confirmação em disparos destes leads. Cancele ou conclua os disparos antes de excluir: '+', '.join(row['name'] for row in dependent))
        fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return {'ids':[row['id'] for row in rows],'leads':[{'id':row['id'],'name':row['name'],'phone':row['phone']} for row in rows],
                'count':len(rows),'fingerprint':fingerprint}

    def preview(self,workspace_id,ids):
        with self.repo.connection() as db:
            return self._preview(db,workspace_id,ids)

    def delete(self,workspace_id,ids,fingerprint):
        with self.repo.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            preview=self._preview(db,workspace_id,ids)
            if not isinstance(fingerprint,str) or fingerprint!=preview['fingerprint']:
                raise LeadConflict('Os leads mudaram desde a revisão. Abra a prévia novamente antes de excluir.')
            marks=','.join('?' for _ in ids)
            db.execute(f'DELETE FROM search_leads WHERE lead_id IN ({marks}) AND search_id IN (SELECT id FROM searches WHERE workspace_id=?)',(*ids,workspace_id))
            db.execute(f'DELETE FROM leads WHERE workspace_id=? AND id IN ({marks})',(workspace_id,*ids))
        return {'deleted':len(ids)}
