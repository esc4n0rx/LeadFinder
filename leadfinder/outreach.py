"""Personalized templates and immutable, workspace-scoped campaign snapshots."""

import re
import threading
from uuid import uuid4

from leadfinder.repository import now
from leadfinder.integrations.whatsapp_runtime import IntegrationError

VARIABLES = ('nome','empresa','telefone','endereco','categoria','site','meu_nome','workspace')
PLACEHOLDER = re.compile(r'{{\s*([a-z_]+)\s*}}')


class OutreachError(ValueError):
    pass


def normalize_phone(value):
    if not isinstance(value, str):
        raise OutreachError('Telefone não informado.')
    digits = re.sub(r'\D', '', value)
    if value.strip().startswith('+'):
        if 8 <= len(digits) <= 15 and digits[0] != '0':
            return digits
    elif len(digits) in (10,11) and digits[:2].isdigit() and int(digits[:2]) >= 11:
        return '55'+digits
    elif len(digits) in (12,13) and digits.startswith('55'):
        return digits
    raise OutreachError('Informe um telefone com DDD. Para números internacionais, use +código do país.')


def validate_template(name, body):
    if not isinstance(name,str) or not 2 <= len(name.strip()) <= 80:
        raise OutreachError('Dê um nome à mensagem entre 2 e 80 caracteres.')
    if not isinstance(body,str) or not 1 <= len(body.strip()) <= 4000:
        raise OutreachError('A mensagem deve ter entre 1 e 4.000 caracteres.')
    for variable in re.findall(r'{{(.*?)}}', body, flags=re.S):
        if variable.strip() not in VARIABLES:
            raise OutreachError('Variável não reconhecida. Use as variáveis disponíveis no editor.')
    remainder = PLACEHOLDER.sub('',body)
    if '{{' in remainder or '}}' in remainder:
        raise OutreachError('Confira as chaves das variáveis da mensagem.')
    return name.strip(),body.strip()


def render_message(body, lead, sender, workspace):
    values = {'nome':lead['name'],'empresa':lead['name'],'telefone':lead.get('phone') or '',
              'endereco':lead.get('address') or '', 'categoria':lead.get('category') or '',
              'site':lead.get('website') or '', 'meu_nome':sender,'workspace':workspace}
    rendered = PLACEHOLDER.sub(lambda match: str(values[match[1]]),body)
    if len(rendered) > 8000:
        raise OutreachError('A mensagem personalizada ultrapassa 8.000 caracteres.')
    return rendered


class OutreachStore:
    def __init__(self, repository):
        self.repo = repository

    def event(self, workspace_id, message, campaign_id=None, level='info', *, connection=None):
        if connection is None:
            with self.repo.connection() as db:
                self.event(workspace_id,message,campaign_id,level,connection=db)
            return
        connection.execute('INSERT INTO outreach_events(workspace_id,campaign_id,level,message,created_at) VALUES(?,?,?,?,?)',
                           (workspace_id,campaign_id,level,message,now()))
        connection.execute('DELETE FROM outreach_events WHERE workspace_id=? AND id NOT IN (SELECT id FROM outreach_events WHERE workspace_id=? ORDER BY id DESC LIMIT 2000)',(workspace_id,workspace_id))

    def events(self, workspace_id, campaign_id=None):
        with self.repo.connection() as db:
            return [dict(row) for row in db.execute(
                'SELECT id,level,message,created_at FROM outreach_events WHERE workspace_id=? AND campaign_id IS ? ORDER BY id DESC LIMIT 100',
                (workspace_id,campaign_id))]

    def integration(self, workspace_id):
        with self.repo.connection() as db:
            row = db.execute('SELECT * FROM whatsapp_integrations WHERE workspace_id=?',(workspace_id,)).fetchone()
            return dict(row) if row else None

    def save_integration(self, workspace_id, name, phone):
        with self.repo.connection() as db:
            db.execute('INSERT INTO whatsapp_integrations(workspace_id,name,phone,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET name=excluded.name,phone=excluded.phone,updated_at=excluded.updated_at',
                       (workspace_id,name,phone,now(),now()))

    def integration_enabled(self, workspace_id, enabled):
        with self.repo.connection() as db:
            db.execute('UPDATE whatsapp_integrations SET enabled=?,updated_at=? WHERE workspace_id=?',(int(enabled),now(),workspace_id))

    def templates(self, workspace_id):
        with self.repo.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM message_templates WHERE workspace_id=? AND archived=0 ORDER BY updated_at DESC,id DESC',(workspace_id,))]

    def template(self, workspace_id, template_id):
        with self.repo.connection() as db:
            row = db.execute('SELECT * FROM message_templates WHERE workspace_id=? AND id=? AND archived=0',(workspace_id,template_id)).fetchone()
            return dict(row) if row else None

    def save_template(self, workspace_id, name, body, template_id=None):
        name,body = validate_template(name,body)
        with self.repo.connection() as db:
            if template_id is not None:
                result = db.execute('UPDATE message_templates SET name=?,body=?,updated_at=? WHERE workspace_id=? AND id=? AND archived=0', (name,body,now(),workspace_id,template_id))
                if not result.rowcount:
                    raise OutreachError('Mensagem não encontrada.')
                return template_id
            return db.execute('INSERT INTO message_templates(workspace_id,name,body,created_at,updated_at) VALUES(?,?,?,?,?) RETURNING id',(workspace_id,name,body,now(),now())).fetchone()['id']

    def archive_template(self, workspace_id, template_id):
        with self.repo.connection() as db:
            return bool(db.execute('UPDATE message_templates SET archived=1 WHERE workspace_id=? AND id=?',(workspace_id,template_id)).rowcount)

    def prepare(self, workspace, user_name, data):
        name = data.get('name','')
        if not isinstance(name,str) or not 2 <= len(name.strip()) <= 80:
            raise OutreachError('Informe um nome para o disparo entre 2 e 80 caracteres.')
        simulated = data.get('simulated',True)
        if type(simulated) is not bool:
            raise OutreachError('Selecione simulação ou envio real.')
        test_target = data.get('test_target',False)
        if type(test_target) is not bool or (test_target and simulated):
            raise OutreachError('O envio ao número de teste exige o modo de envio real.')
        template_ids = data.get('template_ids',[])
        if not isinstance(template_ids,list) or not 1 <= len(template_ids) <= 5 or any(type(item) is not int for item in template_ids) or len(set(template_ids)) != len(template_ids):
            raise OutreachError('Selecione de 1 a 5 mensagens diferentes, na ordem desejada.')
        templates = [self.template(workspace['id'],item) for item in template_ids]
        if not all(templates):
            raise OutreachError('Uma mensagem selecionada não pertence a este workspace ou foi arquivada.')
        integration = self.integration(workspace['id'])
        sender = integration['name'] if integration else user_name
        skipped, targets = [], []
        if simulated or test_target:
            fictional_name = data.get('fictional_name','Café Horizonte (fictício)')
            if not isinstance(fictional_name,str) or not 2 <= len(fictional_name.strip()) <= 80:
                raise OutreachError('O nome do cliente fictício deve ter entre 2 e 80 caracteres.')
            fictional_phone = data.get('fictional_phone','')
            if not isinstance(fictional_phone,str):
                raise OutreachError('Informe o telefone do cliente fictício como texto.')
            phone = normalize_phone(fictional_phone) if fictional_phone.strip() else None
            if test_target and (not integration or not phone):
                raise OutreachError('Configure o WhatsApp e informe o telefone do destinatário de teste para o envio real.')
            targets = [{'key':'fictional','name':fictional_name.strip(),'phone':phone,'address':'Endereço de teste','category':'Cliente fictício','website':'https://example.org'}]
        else:
            if not integration:
                raise OutreachError('Configure sua integração de WhatsApp antes de preparar envios reais.')
            ids = data.get('target_ids',[])
            if not isinstance(ids,list) or not 1 <= len(ids) <= 100 or any(type(item) is not int for item in ids) or len(set(ids)) != len(ids):
                raise OutreachError('Selecione de 1 a 100 estabelecimentos diferentes.')
            seen = set()
            for lead_id in ids:
                lead = self.repo.get_lead(lead_id,workspace['id'])
                if not lead:
                    raise OutreachError('Um destinatário não foi encontrado neste workspace.')
                try:
                    phone = normalize_phone(lead['phone'])
                except OutreachError as error:
                    skipped.append({'name':lead['name'],'reason':str(error)})
                    continue
                if phone in seen:
                    skipped.append({'name':lead['name'],'reason':'Telefone repetido neste disparo.'})
                    continue
                seen.add(phone)
                targets.append({**lead,'key':phone,'phone':phone})
            if not targets:
                raise OutreachError('Nenhum destinatário possui um telefone válido para envio.')
        interval = data.get('interval_seconds',8)
        if type(interval) is not int or not 3 <= interval <= 120:
            raise OutreachError('O intervalo entre mensagens deve ser de 3 a 120 segundos.')
        messages = []
        for target in targets:
            for index, template in enumerate(templates):
                messages.append({'target_key':target['key'],'target_name':target['name'],'phone':target['phone'],
                    'message_index':index,'template_name':template['name'],
                    'body':render_message(template['body'],target,sender,workspace['name'])})
        return {'name':name.strip(),'simulated':simulated,'sender_phone':integration['phone'] if integration else '',
                'interval_seconds':interval,'target_count':len(targets),'message_count':len(messages),'messages':messages,'skipped':skipped}

    def create_campaign(self, workspace_id, prepared):
        campaign_id = uuid4().hex
        with self.repo.connection() as db:
            db.execute('INSERT INTO campaigns(id,workspace_id,name,simulated,sender_phone,interval_seconds,target_count,message_count,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (campaign_id,workspace_id,prepared['name'],int(prepared['simulated']),prepared['sender_phone'],prepared['interval_seconds'],prepared['target_count'],prepared['message_count'],now()))
            db.executemany('INSERT INTO campaign_messages(campaign_id,target_key,target_name,phone,message_index,template_name,body) VALUES(?,?,?,?,?,?,?)',
                [(campaign_id,item['target_key'],item['target_name'],item['phone'],item['message_index'],item['template_name'],item['body']) for item in prepared['messages']])
        self.event(workspace_id,'Simulação local preparada. Nenhuma mensagem será enviada.' if prepared['simulated'] else 'Envio real preparado. Aguardando revisão e início pelo usuário.',campaign_id)
        return campaign_id

    def campaigns(self, workspace_id):
        with self.repo.connection() as db:
            ids = [row[0] for row in db.execute('SELECT id FROM campaigns WHERE workspace_id=? ORDER BY created_at DESC LIMIT 50',(workspace_id,))]
        return [self.campaign(workspace_id,item,include_messages=False) for item in ids]

    def campaign(self, workspace_id, campaign_id, include_messages=True):
        with self.repo.connection() as db:
            row = db.execute('SELECT * FROM campaigns WHERE workspace_id=? AND id=?',(workspace_id,campaign_id)).fetchone()
            if not row:
                return None
            result = dict(row)
            result['counts'] = {item['status']:item['total'] for item in db.execute('SELECT status,COUNT(*) total FROM campaign_messages WHERE campaign_id=? GROUP BY status',(campaign_id,))}
            if include_messages:
                result['messages'] = [dict(item) for item in db.execute('SELECT * FROM campaign_messages WHERE campaign_id=? ORDER BY id',(campaign_id,))]
                result['events'] = self.events(workspace_id,campaign_id)
                result['test_target'] = bool(not result['simulated'] and any(item['target_key']=='fictional' for item in result['messages']))
            return result

    def recover(self):
        with self.repo.connection() as db:
            interrupted = db.execute("SELECT id,workspace_id FROM campaigns WHERE status='running'").fetchall()
            db.execute("UPDATE campaign_messages SET status='uncertain',error='O servidor encerrou durante a tentativa. Confira o WhatsApp antes de repetir.' WHERE status='sending'")
            db.execute("UPDATE campaigns SET status='interrupted',finished_at=?,error='Execução interrompida pelo encerramento do servidor. Não há retomada automática.' WHERE status='running'",(now(),))
            db.execute("UPDATE campaign_jobs SET status='done',updated_at=? WHERE status='running'",(now(),))
        for item in interrupted:
            self.event(item['workspace_id'],'O servidor foi reiniciado durante a execução. Tentativas em andamento ficam sem confirmação; não haverá reenvio automático.',item['id'],level='error')


class IntegrationService:
    def __init__(self, store, provider):
        self.store,self.provider = store,provider
        self.lock = threading.RLock()
        self.operations = {}
        self.restoring = set()
        self.restore_errors = {}
        self.last_states = {}
        if hasattr(provider,'set_state_listener'):
            provider.set_state_listener(self.record_state)

    def operation(self, workspace_id):
        with self.lock:
            return self.operations.setdefault(workspace_id,threading.RLock())

    def restore_sessions(self):
        with self.store.repo.connection() as db:
            ids = [row[0] for row in db.execute('SELECT workspace_id FROM whatsapp_integrations WHERE enabled=1')]
        for workspace_id in ids:
            with self.lock:
                self.restoring.add(workspace_id)
            threading.Thread(target=self._restore,args=(workspace_id,),daemon=True).start()

    def _restore(self, workspace_id):
        try:
            with self.operation(workspace_id):
                config = self.store.integration(workspace_id)
                if not config or not config['enabled']:
                    return
                self.store.event(workspace_id,'Restaurando a sessão salva do WhatsApp após iniciar o servidor.')
                self.provider.connect(workspace_id,config['phone'])
        except IntegrationError as error:
            with self.lock:
                self.restore_errors[workspace_id] = str(error)
            self.store.event(workspace_id,str(error),level='error')
        finally:
            with self.lock:
                self.restoring.discard(workspace_id)

    def save(self, workspace_id, name, phone):
        if not isinstance(name,str) or not 2 <= len(name.strip()) <= 80:
            raise OutreachError('Informe seu nome de envio entre 2 e 80 caracteres.')
        phone = normalize_phone(phone)
        current = self.store.integration(workspace_id)
        if current and current['phone'] != phone and current['enabled']:
            raise OutreachError('Desconecte o WhatsApp antes de trocar o número configurado.')
        self.store.save_integration(workspace_id,name.strip(),phone)
        self.store.event(workspace_id,'Configuração de WhatsApp salva.')

    def status(self, workspace_id):
        config = self.store.integration(workspace_id)
        if not config:
            return {'configured':False,'status':'not_configured','qr':None,'phone':None,'name':'','error':None}
        with self.lock:
            restoring = workspace_id in self.restoring
            restore_error = self.restore_errors.get(workspace_id)
        if restoring:
            state = {'status':'restoring','qr':None,'phone':None,'error':None}
        elif restore_error:
            state = {'status':'error','qr':None,'phone':None,'error':restore_error}
        else:
            try:
                state = self.provider.status(workspace_id)
            except IntegrationError as error:
                state = {'status':'error','qr':None,'phone':None,'error':str(error)}
        if not config['enabled']:
            state = {'status':'disconnected','qr':None,'phone':None,'error':None}
        if state['status'] == 'ready' and state.get('phone') != config['phone']:
            state = {**state,'status':'mismatch','qr':None,'error':'A conta conectada difere do número configurado.'}
        self.record_state(workspace_id,state)
        return {**state,'configured':True,'name':config['name'],'configured_phone':config['phone'],'events':self.store.events(workspace_id)}

    def record_state(self, workspace_id, state):
        labels = {'restoring':'Restaurando sessão salva.','starting':'Iniciando o WhatsApp Web.',
                  'qr':'Aguardando leitura do QR code pelo celular.','authenticating':'QR aceito. Finalizando autenticação.',
                  'ready':'WhatsApp conectado. Envios reais liberados.', 'disconnected':'WhatsApp desconectado. Envios reais bloqueados.',
                  'error':'Falha na conexão do WhatsApp.','mismatch':'A conta conectada difere do número configurado.'}
        with self.lock:
            key = (state['status'],state.get('error'))
            if self.last_states.get(workspace_id) != key:
                self.store.event(workspace_id,state.get('error') or labels.get(state['status'],'Estado da conexão atualizado.'),
                                 level='error' if state['status'] in ('error','mismatch') else 'info')
                self.last_states[workspace_id] = key

    def connect(self, workspace_id):
        config = self.store.integration(workspace_id)
        if not config:
            raise OutreachError('Salve seu nome e número antes de conectar.')
        with self.operation(workspace_id):
            with self.lock:
                self.restore_errors.pop(workspace_id,None)
            self.store.event(workspace_id,'Conexão solicitada. Usando a sessão salva quando disponível.')
            try:
                result = self.provider.connect(workspace_id,config['phone'])
            except IntegrationError as error:
                self.store.event(workspace_id,str(error),level='error')
                raise
            self.store.integration_enabled(workspace_id,True)
            return result

    def disconnect(self, workspace_id):
        with self.operation(workspace_id):
            self.store.integration_enabled(workspace_id,False)
            with self.lock:
                self.restore_errors.pop(workspace_id,None)
            self.provider.disconnect(workspace_id)
            self.store.event(workspace_id,'Desconectado pelo usuário. A sessão salva foi removida.')

    def require_ready(self, workspace_id, sender_phone):
        state = self.status(workspace_id)
        if state['status'] != 'ready' or state.get('phone') != sender_phone:
            raise IntegrationError('Conecte o WhatsApp do número configurado para iniciar ou continuar este envio.')
