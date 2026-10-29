"""Sequential campaign execution with durable per-message outcomes and cancellation."""

import sqlite3
import threading
import time
from datetime import datetime,timedelta,timezone

from leadfinder.integrations.whatsapp_runtime import DeliveryUncertain, IntegrationError
from leadfinder.outreach import OutreachError
from leadfinder.repository import now


class CampaignService:
    def __init__(self, store, integration):
        self.store,self.integration = store,integration

    def start(self, workspace_id, campaign_id, *, resume=False, scheduled=False):
        campaign = self.store.campaign(workspace_id,campaign_id)
        if not campaign:
            raise OutreachError('Disparo não encontrado.')
        if resume and (not campaign['counts'].get('pending') or campaign['counts'].get('uncertain') or campaign['counts'].get('sending')):
            raise OutreachError('Verifique as tentativas sem confirmação antes de retomar. Somente mensagens pendentes podem ser enviadas.')
        if not campaign['simulated']:
            try:
                self.integration.require_ready(workspace_id,campaign['sender_phone'])
            except IntegrationError as error:
                self.store.event(workspace_id,'Início bloqueado: '+str(error),campaign_id,level='error')
                raise
        try:
            with self.store.repo.connection() as db:
                allowed=('paused','interrupted','partial') if resume else ('scheduled',) if scheduled else ('draft',)
                changed = db.execute("UPDATE campaigns SET status='running',error=NULL,finished_at=NULL,cancel_requested=0,pause_requested=0 WHERE workspace_id=? AND id=? AND status IN ("+','.join('?' for _ in allowed)+")",(workspace_id,campaign_id,*allowed)).rowcount
                if not changed:
                    raise OutreachError('Este disparo já foi executado ou cancelado. Crie um novo rascunho para outra tentativa.')
                db.execute("INSERT INTO campaign_jobs VALUES(?,?,?,'running',?) ON CONFLICT(campaign_id) DO UPDATE SET status='running',updated_at=excluded.updated_at",(campaign_id,workspace_id,now(),now()))
        except sqlite3.IntegrityError as error:
            raise OutreachError('Já existe um disparo em andamento neste workspace.') from error
        try:
            self.store.event(workspace_id,'Simulação local iniciada. Nenhum envio será feito.' if campaign['simulated'] else 'Envio real iniciado.',campaign_id)
            threading.Thread(target=self._run,args=(workspace_id,campaign_id),daemon=True).start()
        except Exception:
            self._finish(campaign_id,'interrupted','Não foi possível iniciar o processamento.')
            raise

    def cancel(self, workspace_id, campaign_id):
        with self.store.repo.connection() as db:
            db.execute("UPDATE campaigns SET cancel_requested=1,status=CASE WHEN status!='running' THEN 'cancelled' ELSE status END,finished_at=CASE WHEN status!='running' THEN ? ELSE finished_at END WHERE workspace_id=? AND id=? AND status IN ('draft','running','scheduled','paused','interrupted','partial')",(now(),workspace_id,campaign_id))
            db.execute("UPDATE campaign_jobs SET status='done',updated_at=? WHERE campaign_id=? AND workspace_id=? AND status='queued'",(now(),campaign_id,workspace_id))
        self.store.event(workspace_id,'Cancelamento solicitado pelo usuário.',campaign_id)

    def pause(self,workspace_id,campaign_id):
        with self.store.repo.connection() as db:
            if not db.execute("UPDATE campaigns SET pause_requested=1 WHERE workspace_id=? AND id=? AND status='running'",(workspace_id,campaign_id)).rowcount:
                raise OutreachError('Somente um disparo em andamento pode ser pausado.')
        self.store.event(workspace_id,'Pausa solicitada. Uma tentativa em andamento pode terminar.',campaign_id)

    def schedule(self,workspace_id,campaign_id,due_at):
        from leadfinder.crm import utc_time
        from leadfinder.lead_directory import DirectoryError
        try:
            due=utc_time(due_at,future=True)
        except DirectoryError as error:
            raise OutreachError(str(error)) from error
        with self.store.repo.connection() as db:
            if not db.execute("UPDATE campaigns SET status='scheduled',scheduled_at=? WHERE workspace_id=? AND id=? AND status='draft'",(due,workspace_id,campaign_id)).rowcount:
                raise OutreachError('Somente um rascunho revisado pode ser agendado.')
            db.execute("INSERT INTO campaign_jobs VALUES(?,?,?,'queued',?)",(campaign_id,workspace_id,due,now()))
            self.store.event(workspace_id,'Disparo agendado para '+due+'. O LeadFinder precisa estar em execução.',campaign_id,connection=db)

    def process_due(self,workspace_id):
        with self.store.repo.connection() as db:
            jobs=db.execute("SELECT * FROM campaign_jobs WHERE workspace_id=? AND status='queued' AND available_at<=? ORDER BY available_at LIMIT 10",(workspace_id,now())).fetchall()
        for job in jobs:
            try:
                self.start(job['workspace_id'],job['campaign_id'],scheduled=True)
            except (IntegrationError,OutreachError):
                with self.store.repo.connection() as db:
                    db.execute("UPDATE campaign_jobs SET available_at=?,updated_at=? WHERE campaign_id=? AND status='queued'",((datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat(),now(),job['campaign_id']))

    def reconcile(self,workspace_id,campaign_id,message_id,resolution=None):
        campaign=self.store.campaign(workspace_id,campaign_id)
        if not campaign or campaign['status'] not in ('paused','interrupted','partial'):
            raise OutreachError('Abra um disparo pausado ou interrompido para verificar suas tentativas.')
        message=next((m for m in campaign['messages'] if m['id']==message_id),None)
        if not message or message['status']!='uncertain':
            raise OutreachError('Esta mensagem não está aguardando confirmação.')
        if resolution is not None:
            if resolution not in ('sent','failed'):
                raise OutreachError('Resolução inválida.')
            status=resolution
            detail='Resultado verificado manualmente pelo usuário: '+('enviada.' if status=='sent' else 'não enviada; tentativa encerrada sem repetição.')
        else:
            self.integration.require_ready(workspace_id,campaign['sender_phone'])
            verify=getattr(self.integration.provider,'verify',None)
            if not verify or not message['provider_id']:
                raise OutreachError('Esta tentativa não tem um identificador consultável. Confira no celular e registre o resultado manualmente.')
            result=verify(workspace_id,message['provider_id'],campaign['sender_phone'])
            if not isinstance(result,dict) or type(result.get('ack')) is not int or result['ack']<1:
                raise OutreachError('Ainda não há confirmação do servidor para esta mensagem. Nenhum reenvio foi feito.')
            status='sent';detail='Confirmação recuperada consultando a mesma mensagem. Nenhum reenvio foi feito.'
        with self.store.repo.connection() as db:
            changed=db.execute("UPDATE campaign_messages SET status=?,error=NULL,sent_at=? WHERE id=? AND campaign_id=? AND status='uncertain'",(status,now() if status=='sent' else None,message_id,campaign_id)).rowcount
            if not changed:
                raise OutreachError('O resultado já foi alterado. Atualize o disparo.')
            if status=='sent' and message['target_key']!='fictional' and not campaign['simulated']:
                from leadfinder.lead_directory import record_outgoing
                record_outgoing(db,workspace_id,message['phone'])
            self.store.event(workspace_id,detail,campaign_id,connection=db)
            db.execute('UPDATE campaigns SET error=? WHERE id=?',('Tentativa verificada. Retome as mensagens pendentes quando desejar.',campaign_id))

    def _finish(self, campaign_id, status, error=None):
        with self.store.repo.connection() as db:
            db.execute('UPDATE campaigns SET status=?,error=?,finished_at=? WHERE id=?',(status,error,now(),campaign_id))
            db.execute("UPDATE campaign_jobs SET status='done',updated_at=? WHERE campaign_id=?",(now(),campaign_id))
            row = db.execute('SELECT workspace_id,simulated FROM campaigns WHERE id=?',(campaign_id,)).fetchone()
            summary = ('Simulação finalizada. Nenhuma mensagem foi enviada.' if row['simulated'] else 'Todas as mensagens foram aceitas pelo servidor do WhatsApp. Entrega e leitura não foram confirmadas.') if status=='completed' else 'Execução encerrada: '+status+'.'
            self.store.event(row['workspace_id'],error or summary,campaign_id,level='error' if status in ('paused','interrupted','failed','partial') else 'info',connection=db)

    def _message(self, message_id, status, error=None, provider_id=None):
        with self.store.repo.connection() as db:
            db.execute('UPDATE campaign_messages SET status=?,error=?,provider_id=?,sent_at=? WHERE id=?',
                       (status,error,provider_id,now() if status in ('sent','simulated') else None,message_id))
            if status=='sent':
                message=db.execute('''SELECT c.workspace_id,c.simulated,m.phone,m.target_key
                    FROM campaign_messages m JOIN campaigns c ON c.id=m.campaign_id WHERE m.id=?''',(message_id,)).fetchone()
                if message and not message['simulated'] and message['target_key']!='fictional':
                    from leadfinder.lead_directory import record_outgoing
                    record_outgoing(db,message['workspace_id'],message['phone'])

    def _run(self, workspace_id, campaign_id):
        current_id = None
        try:
            campaign = self.store.campaign(workspace_id,campaign_id)
            failed = campaign['counts'].get('failed',0)
            for index,message in enumerate(campaign['messages']):
                if message['status'] != 'pending':
                    continue
                fresh = self.store.campaign(workspace_id,campaign_id,False)
                if fresh['cancel_requested']:
                    self._finish(campaign_id,'cancelled')
                    return
                if fresh['pause_requested']:
                    self._finish(campaign_id,'paused','Pausado pelo usuário. Mensagens pendentes preservadas.')
                    return
                while fresh['next_send_at'] and fresh['next_send_at']>now():
                    time.sleep(.05 if campaign['simulated'] else .25)
                    fresh=self.store.campaign(workspace_id,campaign_id,False)
                    if fresh['cancel_requested'] or fresh['pause_requested']:
                        self._finish(campaign_id,'cancelled' if fresh['cancel_requested'] else 'paused','Execução interrompida pelo usuário. Pendentes preservadas.')
                        return
                if not campaign['simulated']:
                    self.integration.require_ready(workspace_id,campaign['sender_phone'])
                with self.store.repo.connection() as db:
                    changed = db.execute("UPDATE campaign_messages SET status='sending' WHERE id=? AND status='pending'",(message['id'],)).rowcount
                if not changed:
                    continue
                current_id = message['id']
                self.store.event(workspace_id,f'Mensagem {index+1}/{len(campaign["messages"])}: '+('simulando localmente.' if campaign['simulated'] else 'enviando ao WhatsApp.'),campaign_id)
                if campaign['simulated']:
                    # Simulation never reaches the provider, even with a configured phone.
                    self._message(current_id,'simulated')
                else:
                    try:
                        provider_id = self.integration.provider.send(workspace_id,message['phone'],message['body'],campaign['sender_phone'])
                        if not isinstance(provider_id,str) or not provider_id.strip():
                            raise DeliveryUncertain('O provedor não confirmou um identificador para a mensagem. Confira o WhatsApp antes de repetir.')
                        self._message(current_id,'sent',provider_id=provider_id)
                        self.store.event(workspace_id,f'Mensagem {index+1}: aceita pelo servidor do WhatsApp.',campaign_id)
                    except DeliveryUncertain as error:
                        self._message(current_id,'uncertain',str(error),provider_id=error.provider_id)
                        self._finish(campaign_id,'paused',str(error))
                        return
                    except IntegrationError as error:
                        failed += 1
                        self._message(current_id,'failed',str(error))
                        self.store.event(workspace_id,f'Mensagem {index+1}: '+str(error),campaign_id,level='error')
                current_id = None
                with self.store.repo.connection() as db:
                    db.execute('UPDATE campaigns SET next_send_at=? WHERE id=?',((datetime.now(timezone.utc)+timedelta(seconds=.05 if campaign['simulated'] else campaign['interval_seconds'])).isoformat(),campaign_id))
                if index < len(campaign['messages'])-1:
                    deadline = time.monotonic() + (.05 if campaign['simulated'] else campaign['interval_seconds'])
                    while time.monotonic() < deadline:
                        fresh=self.store.campaign(workspace_id,campaign_id,False)
                        if fresh['cancel_requested'] or fresh['pause_requested']:
                            self._finish(campaign_id,'cancelled' if fresh['cancel_requested'] else 'paused','Execução interrompida pelo usuário. Pendentes preservadas.')
                            return
                        time.sleep(min(.25,max(0,deadline-time.monotonic())))
            self._finish(campaign_id,('failed' if failed==len(campaign['messages']) else 'partial') if failed else 'completed')
        except IntegrationError as error:
            if current_id:
                self._message(current_id,'uncertain',str(error))
            self._finish(campaign_id,'paused',str(error))
        except Exception:
            if current_id:
                self._message(current_id,'uncertain','Não foi possível confirmar o resultado. Confira no WhatsApp antes de repetir.')
            self._finish(campaign_id,'interrupted','O processamento foi interrompido. Consulte os resultados antes de criar outro disparo.')
