"""Lead history, sales stages, bulk organization, and follow-up reminders."""
from datetime import datetime, timezone

from leadfinder.lead_directory import DirectoryError, LeadDirectory, phone_key
from leadfinder.repository import now

STAGES={'new':'Novo','contacted':'Contatado','replied':'Respondeu','demo':'Demonstração','customer':'Cliente','lost':'Perdido'}


def utc_time(value, *, future=False):
    try:
        if not isinstance(value,str) or len(value)>40:
            raise ValueError()
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        if stamp.tzinfo is None:
            raise ValueError()
        stamp=stamp.astimezone(timezone.utc)
        if future and stamp<=datetime.now(timezone.utc):
            raise ValueError()
        return stamp.isoformat()
    except (ValueError,TypeError,OverflowError):
        raise DirectoryError('Informe uma data e hora válidas com fuso horário'+(' no futuro.' if future else '.')) from None


def validate_ids(ids,limit=1000):
    if not isinstance(ids,list) or not 1<=len(ids)<=limit or any(type(item) is not int or item<1 for item in ids) or len(set(ids))!=len(ids):
        raise DirectoryError(f'Selecione de 1 a {limit} leads diferentes.')
    return ids


def lead_event(db, workspace_id, lead_id, kind, body):
    db.execute('INSERT INTO lead_events(workspace_id,lead_id,kind,body,created_at) VALUES(?,?,?,?,?)',
               (workspace_id,lead_id,kind,body,now()))


class CRM:
    def __init__(self,repo):
        self.repo=repo

    def require_leads(self,db,workspace_id,ids):
        validate_ids(ids)
        marks=','.join('?' for _ in ids)
        rows=db.execute(f'SELECT id FROM leads WHERE workspace_id=? AND id IN ({marks})',(workspace_id,*ids)).fetchall()
        if len(rows)!=len(ids):
            raise LookupError('Um lead não pertence a este workspace.')

    def stage(self,workspace_id,ids,stage):
        return self.bulk(workspace_id,ids,{'stage':stage})

    def bulk(self,workspace_id,ids,data):
        validate_ids(ids)
        if not isinstance(data,dict) or not data or not set(data)<={'stage','contact_status','category_ids','category_mode'}:
            raise DirectoryError('Escolha uma alteração para os leads selecionados.')
        if 'stage' in data and (not isinstance(data['stage'],str) or data['stage'] not in STAGES):
            raise DirectoryError('Etapa comercial inválida.')
        if 'contact_status' in data and data['contact_status'] not in ('new','contacted','conversed'):
            raise DirectoryError('Status inválido.')
        mode=data.get('category_mode','add')
        if mode not in ('add','replace','remove'):
            raise DirectoryError('Operação de categorias inválida.')
        categories=data.get('category_ids')
        if categories is not None:
            if categories==[] and mode=='replace':
                pass
            else:
                validate_ids(categories,100)
        elif 'category_ids' in data or set(data)=={'category_mode'}:
            raise DirectoryError('Selecione as categorias.')
        with self.repo.connection() as db:
            self.require_leads(db,workspace_id,ids)
            if categories is not None:
                available={r[0] for r in db.execute('SELECT id FROM lead_categories WHERE workspace_id=?',(workspace_id,))}
                if not set(categories)<=available:
                    raise DirectoryError('Categoria não encontrada neste workspace.')
            for lead_id in ids:
                if categories is not None:
                    if mode=='replace':
                        db.execute('DELETE FROM lead_category_links WHERE workspace_id=? AND lead_id=?',(workspace_id,lead_id))
                    for category in categories:
                        if mode=='remove':
                            db.execute('DELETE FROM lead_category_links WHERE workspace_id=? AND lead_id=? AND category_id=?',(workspace_id,lead_id,category))
                        else:
                            db.execute('INSERT OR IGNORE INTO lead_category_links VALUES(?,?,?)',(workspace_id,lead_id,category))
                    lead_event(db,workspace_id,lead_id,'categories','Categorias atualizadas em lote.')
                contact=data.get('contact_status')
                if 'stage' in data:
                    db.execute('''INSERT INTO lead_profiles VALUES(?,?,?,?) ON CONFLICT(lead_id)
                        DO UPDATE SET stage=excluded.stage,updated_at=excluded.updated_at''',(lead_id,workspace_id,data['stage'],now()))
                    lead_event(db,workspace_id,lead_id,'stage','Etapa: '+STAGES[data['stage']])
                    if contact is None:
                        contact={'new':'new','contacted':'contacted','replied':'conversed','demo':'conversed','customer':'conversed'}.get(data['stage'])
                if contact is not None:
                    db.execute('''INSERT INTO lead_contacts VALUES(?,?,?,?) ON CONFLICT(lead_id)
                        DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at''',(lead_id,workspace_id,contact,now()))
                    lead_event(db,workspace_id,lead_id,'contact','Status do contato atualizado: '+{'new':'Sem contato','contacted':'Contato iniciado','conversed':'Já houve conversa'}[contact])
        return {'updated':len(ids)}

    def dossier(self,workspace_id,lead_id):
        lead=self.repo.get_lead(lead_id,workspace_id)
        if not lead:
            raise LookupError('Lead não encontrado.')
        with self.repo.connection() as db:
            stage=db.execute('SELECT stage FROM lead_profiles WHERE workspace_id=? AND lead_id=?',(workspace_id,lead_id)).fetchone()
            lead['stage']=stage[0] if stage else 'new'
            lead['notes']=[dict(row) for row in db.execute('SELECT * FROM lead_notes WHERE workspace_id=? AND lead_id=? ORDER BY id DESC LIMIT 100',(workspace_id,lead_id))]
            lead['reminders']=[dict(row) for row in db.execute('SELECT * FROM reminders WHERE workspace_id=? AND lead_id=? ORDER BY completed_at IS NOT NULL,due_at,id LIMIT 100',(workspace_id,lead_id))]
            timeline=[dict(row) for row in db.execute('SELECT id,kind,body,created_at FROM lead_events WHERE workspace_id=? AND lead_id=? ORDER BY id DESC LIMIT 200',(workspace_id,lead_id))]
            db.create_function('lead_phone',1,phone_key,deterministic=True)
            messages=db.execute('''SELECT m.*,c.name AS campaign_name,c.created_at AS campaign_created
                FROM campaign_messages m JOIN campaigns c ON c.id=m.campaign_id
                WHERE c.workspace_id=? AND c.simulated=0 AND m.target_key!='fictional' AND m.phone=lead_phone(?)
                ORDER BY m.id DESC LIMIT 200''',(workspace_id,lead['phone'])).fetchall()
            lead['messages']=[dict(row) for row in messages]
            timeline.extend({'kind':'message','body':row['body'],'created_at':row['sent_at'] or row['campaign_created'],
                             'status':row['status'],'campaign_id':row['campaign_id'],'campaign_name':row['campaign_name']} for row in messages)
        timeline.append({'kind':'discovery','body':'Estabelecimento encontrado no Google Maps.','created_at':lead['first_seen_at']})
        lead['timeline']=sorted(timeline,key=lambda item:item['created_at'],reverse=True)[:300]
        return lead

    def note(self,workspace_id,lead_id,body):
        if not isinstance(body,str) or not 1<=len(body.strip())<=4000:
            raise DirectoryError('Escreva uma anotação entre 1 e 4.000 caracteres.')
        with self.repo.connection() as db:
            self.require_leads(db,workspace_id,[lead_id])
            identity=db.execute('INSERT INTO lead_notes(workspace_id,lead_id,body,created_at) VALUES(?,?,?,?)',(workspace_id,lead_id,body.strip(),now())).lastrowid
            lead_event(db,workspace_id,lead_id,'note',body.strip())
        return identity

    def reminder(self,workspace_id,lead_id,title,due_at):
        if not isinstance(title,str) or not 2<=len(title.strip())<=160:
            raise DirectoryError('O lembrete deve ter entre 2 e 160 caracteres.')
        due=utc_time(due_at)
        with self.repo.connection() as db:
            self.require_leads(db,workspace_id,[lead_id])
            identity=db.execute('INSERT INTO reminders(workspace_id,lead_id,title,due_at,created_at) VALUES(?,?,?,?,?)',(workspace_id,lead_id,title.strip(),due,now())).lastrowid
            lead_event(db,workspace_id,lead_id,'reminder',title.strip()+' · '+due)
        return identity

    def reminders(self,workspace_id,mode='pending'):
        if mode not in ('pending','overdue','completed','all'):
            raise DirectoryError('Filtro de lembretes inválido.')
        condition={'pending':'r.completed_at IS NULL','overdue':'r.completed_at IS NULL AND r.due_at<?','completed':'r.completed_at IS NOT NULL','all':'1=1'}[mode]
        with self.repo.connection() as db:
            return [dict(row) for row in db.execute(f'''SELECT r.*,l.name AS lead_name FROM reminders r JOIN leads l
                ON l.id=r.lead_id AND l.workspace_id=r.workspace_id WHERE r.workspace_id=? AND {condition}
                ORDER BY r.completed_at IS NOT NULL,r.due_at,r.id LIMIT 500''',(workspace_id,now()) if mode=='overdue' else (workspace_id,))]

    def complete_reminder(self,workspace_id,reminder_id,completed):
        if type(completed) is not bool:
            raise DirectoryError('Informe se o lembrete foi concluído.')
        with self.repo.connection() as db:
            row=db.execute('SELECT * FROM reminders WHERE id=? AND workspace_id=?',(reminder_id,workspace_id)).fetchone()
            if not row:
                raise LookupError('Lembrete não encontrado.')
            db.execute('UPDATE reminders SET completed_at=? WHERE id=?',(now() if completed else None,reminder_id))
            lead_event(db,workspace_id,row['lead_id'],'reminder','Lembrete '+('concluído: ' if completed else 'reaberto: ')+row['title'])

    def context(self,workspace_id,data=None):
        fields=('product','differentials','audience','offer','tone')
        if data is not None:
            if not isinstance(data,dict) or set(data)!=set(fields) or any(not isinstance(data[f],str) or len(data[f])>2000 for f in fields):
                raise DirectoryError('Preencha os campos do produto com até 2.000 caracteres cada.')
            import json
            with self.repo.connection() as db:
                db.execute('INSERT INTO product_context VALUES(?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at',
                           (workspace_id,json.dumps({f:data[f].strip() for f in fields},ensure_ascii=False),now()))
        import json
        with self.repo.connection() as db:
            row=db.execute('SELECT data FROM product_context WHERE workspace_id=?',(workspace_id,)).fetchone()
            return json.loads(row[0]) if row else dict.fromkeys(fields,'')
