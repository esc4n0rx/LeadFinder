"""CRM, recovery, durable schedules, and encrypted portable workspace backups."""
import io
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import threading
import unittest
from uuid import uuid4
from unittest.mock import patch
import zipfile

from cryptography.fernet import Fernet
from leadfinder import create_app
from leadfinder.ai.providers import AIProviders
from leadfinder.backups import seal,unseal,BackupError
from leadfinder.integrations.whatsapp_runtime import DeliveryUncertain
from leadfinder.models import Lead
from tests import test_outreach as helpers
from tests.test_ai import FakeAITransport


class GrowthTest(unittest.TestCase):
    setUp=helpers.OutreachTest.setUp
    tearDown=helpers.OutreachTest.tearDown
    make_account=helpers.OutreachTest.make_account
    post=helpers.OutreachTest.post
    connect=helpers.OutreachTest.connect
    lead=helpers.OutreachTest.lead
    template=helpers.OutreachTest.template
    campaign=helpers.OutreachTest.campaign
    wait=helpers.OutreachTest.wait

    def test_bulk_selection_stage_isolation_and_dossier(self):
        lead=self.lead();other=self.lead('other')
        category=self.post('/api/categories',{'name':'Prioridade'}).json['id']
        result=self.post('/api/leads/bulk',{'ids':[lead,other],'changes':{'category_ids':[category],'stage':'demo'}})
        self.assertEqual(result.json['updated'],2)
        ids=self.post('/api/leads/selection',{'filters':{'category_id':category,'stage':'demo','only_phone':True}}).json['ids']
        self.assertEqual(set(ids),{lead,other})
        brief=self.post('/api/leads/brief',{'ids':ids})
        self.assertIn('2 leads',brief.json['brief']);self.assertIn('Prioridade',brief.json['brief'])
        self.assertEqual(self.client.get('/api/leads?stage=demo').json['total'],2)
        bob,_=self.make_account('bob')
        self.assertEqual(self.post('/api/leads/bulk',{'ids':[lead],'changes':{'stage':'lost'}},bob).status_code,404)
        self.assertEqual(bob.get(f'/api/leads/{lead}/dossier').status_code,404)
        self.assertEqual(self.post('/api/leads/brief',{'ids':ids},bob).status_code,404)
        for bad in ({'stage':[]},{'category_ids':[True]},{'category_ids':[9999]},{'contact_status':'bad'}):
            self.assertEqual(self.post('/api/leads/bulk',{'ids':[lead],'changes':bad}).status_code,400)
        self.post(f'/api/leads/{lead}/notes',{'body':'Interessado no plano anual.'})
        self.post(f'/api/leads/{lead}/reminders',{'title':'Ligar amanhã','due_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()})
        dossier=self.client.get(f'/api/leads/{lead}/dossier').json
        self.assertEqual(dossier['stage'],'demo');self.assertEqual(dossier['contact_status'],'conversed')
        self.assertEqual(dossier['notes'][0]['body'],'Interessado no plano anual.')
        self.assertTrue(dossier['next_action']);self.assertTrue(any(item['kind']=='note' for item in dossier['timeline']))
        reminder=self.client.get('/api/reminders?filter=overdue').json['items'][0]
        self.assertEqual(self.post('/api/reminders/'+str(reminder['id']),{'completed':True},bob).status_code,404)
        self.assertEqual(self.post('/api/reminders/'+str(reminder['id']),{'completed':True}).status_code,200)
        self.assertEqual(self.client.get('/api/reminders?filter=overdue').json['items'],[])
        board=self.client.get('/api/crm/board').json
        self.assertEqual(next(c for c in board['columns'] if c['stage']=='demo')['total'],2)

    def test_csv_selection_and_formula_escaping(self):
        self.repo.create_search('csv','Test','Rio',10,workspace_id=self.workspace)
        self.repo.save_lead('csv',Lead('formula','=HYPERLINK("https://example.org")','https://example.org',phone='+5521988882222'))
        lead=self.repo.list_leads(workspace_id=self.workspace)['items'][0]['id']
        response=self.post('/api/leads/export',{'ids':[lead]})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.data.startswith(b'\xef\xbb\xbf'))
        self.assertIn("'=HYPERLINK",response.data.decode('utf-8-sig'))
        bob,_=self.make_account('bob')
        self.assertEqual(self.post('/api/leads/export',{'ids':[lead]},bob).status_code,404)
        self.assertEqual(self.post('/api/leads/selection',{'filters':{'stage':[]}}).status_code,400)

    def test_brief_remains_within_chat_limit_for_long_external_categories(self):
        self.repo.create_search('brief','Test','Rio',30,workspace_id=self.workspace)
        for index in range(25):
            self.repo.save_lead('brief',Lead('brief-'+str(index),'Empresa '+str(index),'https://example.org',category=str(index)+' '+('category '*200)))
        response=self.post('/api/leads/brief',{'filters':{}})
        self.assertEqual(response.status_code,200)
        self.assertLessEqual(len(response.json['brief']),6000)
        self.assertIn('25 leads',response.json['brief'])

    def test_product_context_is_scoped_injected_and_snapshotted(self):
        transport=FakeAITransport();self.app.extensions['ai_service'].providers=AIProviders(transport)
        context={'product':'OctaMenu','differentials':'Cardápio e pedidos','audience':'Pizzarias','offer':'Agendar demonstração','tone':'Profissional'}
        self.assertEqual(self.post('/api/product-context',context).status_code,200)
        bob,_=self.make_account('bob')
        self.assertEqual(bob.get('/api/product-context').json['product'],'')
        self.post('/api/integrations/ai/openai',{'api_key':'fixture-test-key-12345678','model':'gpt-6.1-terra'})
        thread=self.post('/api/ai/threads').json['id']
        result=self.post(f'/api/ai/threads/{thread}/chat',{'provider':'openai','message':'Crie um contato para pizzarias','request_key':uuid4().hex})
        self.assertEqual(result.json['status'],'completed')
        payload=next(call[3] for call in reversed(transport.calls) if call[0]=='POST')
        self.assertIn('OctaMenu',json.dumps(payload,ensure_ascii=False))
        self.assertIn('OctaMenu',result.json['context_snapshot'])
        self.assertFalse(self.provider.sent)

    def test_uncertain_verification_resume_only_pending_and_timeline(self):
        self.connect();lead=self.lead();templates=[self.template(),self.template('Segunda mensagem','Segunda')]
        def uncertain():
            raise DeliveryUncertain('Aguardando confirmação','true_fixture@c.us_FIXTURE_out')
        self.provider.hook=uncertain
        campaign=self.campaign(templates,False,[lead]);path='/api/campaigns/'+campaign['id']
        self.post(path+'/start');paused=self.wait(campaign['id'])
        self.assertEqual(self.post(path+'/resume').status_code,400)
        self.provider.verify=lambda *args:{'ack':1}
        self.assertEqual(self.post(path+'/messages/'+str(paused['messages'][0]['id'])+'/verify').status_code,200)
        self.assertEqual(len(self.provider.sent),1,'Verification must never send')
        self.provider.hook=None
        self.assertEqual(self.post(path+'/resume').status_code,202)
        result=self.wait(campaign['id']);self.assertEqual(result['counts'],{'sent':2})
        self.assertEqual(len(self.provider.sent),2,'Only the previously pending message is sent')
        self.assertEqual(self.post(path+'/resume').status_code,400)
        dossier=self.client.get(f'/api/leads/{lead}/dossier').json
        self.assertEqual(len(dossier['messages']),2)
        self.assertEqual(dossier['contact_status'],'contacted')

    def test_schedule_survives_restart_and_is_claimed_once(self):
        self.connect();lead=self.lead();campaign=self.campaign([self.template()],False,[lead])
        path='/api/campaigns/'+campaign['id'];due=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        self.assertEqual(self.post(path+'/schedule',{'due_at':'2020-01-01T00:00:00+00:00'}).status_code,400)
        self.assertEqual(self.post(path+'/schedule',{'due_at':due}).status_code,202)
        self.app.extensions['scheduler'].tick();self.assertFalse(self.provider.sent)
        restarted=create_app({'TESTING':True,'DATABASE':self.repo.database},whatsapp_provider=self.provider)
        self.assertEqual(self.store.campaign(self.workspace,campaign['id'])['status'],'scheduled')
        with self.repo.connection() as db:
            db.execute('UPDATE campaign_jobs SET available_at=? WHERE campaign_id=?',('2020-01-01T00:00:00+00:00',campaign['id']))
        restarted.extensions['scheduler'].tick();self.assertEqual(self.wait(campaign['id'])['counts'],{'sent':1})
        restarted.extensions['scheduler'].tick();self.assertEqual(len(self.provider.sent),1)
        self.assertFalse(restarted.extensions['scheduler'].thread)

    def test_pause_does_not_resend_confirmed_messages(self):
        self.connect();lead=self.lead();campaign=self.campaign([self.template(),self.template('Segunda','Segunda')],False,[lead])
        entered=threading.Event();release=threading.Event()
        def blocked():
            entered.set();release.wait(5);return 'fixture-confirmed'
        self.provider.hook=blocked;path='/api/campaigns/'+campaign['id']
        try:
            self.post(path+'/start');self.assertTrue(entered.wait(3))
            self.assertEqual(self.post(path+'/pause').status_code,200)
        finally:
            release.set()
        self.assertEqual(self.wait(campaign['id'])['counts'],{'sent':1,'pending':1})
        self.provider.hook=None;self.post(path+'/resume')
        self.assertEqual(self.wait(campaign['id'])['counts'],{'sent':2})
        self.assertEqual(len(self.provider.sent),2)

    def test_backup_encryption_preview_remapping_and_integrations(self):
        lead=self.lead();self.template();self.connect()
        self.repo.update_search('lead-search-'+str(self.workspace),status='completed')
        self.post('/api/leads/'+str(lead)+'/notes',{'body':'Anotação preservada'})
        self.post('/api/integrations/ai/openai',{'api_key':'fixture-secret-key-12345678','model':'gpt-6.1-terra'})
        profile=Path(self.repo.database).parent/'whatsapp'/f'session-workspace-{self.workspace}'/'Default'/'IndexedDB'
        profile.mkdir(parents=True);(profile/'fixture.bin').write_bytes(b'fixture-session-data')
        password='backup-password-123';backup=self.post('/api/backups/export',{'password':password})
        self.assertEqual(backup.status_code,200,backup.json)
        self.assertNotIn(b'fixture-secret',backup.data)
        files=zipfile.ZipFile(io.BytesIO(unseal(backup.data,password)))
        self.assertNotEqual(files.read('ai-key'),self.app.extensions['ai_service'].vault.path.read_bytes())
        files.close()
        bob,bob_workspace=self.make_account('bob')
        old_bob=self.lead('bob-old',workspace=bob_workspace)
        self.repo.update_search('bob-old-search-'+str(bob_workspace),status='completed')
        with bob.session_transaction() as session:
            csrf=session['csrf']
        def preview(raw,secret=password):
            return bob.post('/api/backups/preview',data={'file':(io.BytesIO(raw),'workspace.lfbackup'),'password':secret,'csrf_token':csrf},content_type='multipart/form-data')
        self.assertEqual(preview(backup.data,'incorrect-password').status_code,400)
        response=preview(backup.data);self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['counts']['leads'],1);self.assertTrue(response.json['whatsapp_session'])
        token=response.json['token'];restore={'token':token,'password':password,'confirmation':'bob workspace','account_password':'test-password-123'}
        self.assertEqual(self.post('/api/backups/restore',restore).status_code,400,'Token is bound to receiving workspace/user')
        self.assertEqual(self.post('/api/backups/restore',{**restore,'confirmation':'wrong'},bob).status_code,400)
        self.assertEqual(self.post('/api/backups/restore',restore,bob).status_code,200)
        self.assertEqual(self.repo.stats(self.workspace)['total'],1,'Original workspace preserved')
        self.assertEqual(self.repo.stats(bob_workspace)['total'],1)
        restored=self.repo.list_leads(workspace_id=bob_workspace)['items'][0]
        self.assertEqual(restored['name'],'Café lead');self.assertNotEqual(restored['id'],lead)
        self.assertEqual(self.app.extensions['ai_service'].require_config(bob_workspace,'openai')[1],'fixture-secret-key-12345678')
        self.assertEqual((Path(self.repo.database).parent/'whatsapp'/f'session-workspace-{bob_workspace}'/'Default'/'IndexedDB'/'fixture.bin').read_bytes(),b'fixture-session-data')
        self.assertEqual(self.store.integration(bob_workspace)['enabled'],0)
        self.assertEqual(self.post('/api/backups/restore',restore,bob).status_code,400,'Preview is consumed once')
        recovery=bob.get('/api/backups/recovery');self.assertEqual(recovery.status_code,200)
        recovery.close()
        self.assertFalse(self.provider.sent)

    def test_backup_path_traversal_and_mutation_gate(self):
        lead=self.lead();password='backup-password-123'
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as archive:
            archive.writestr('../escape.txt','bad')
        with self.assertRaises(BackupError):
            self.app.extensions['backups'].unpack(seal(raw.getvalue(),password),password)
        with self.app.extensions['workspace_gate'].exclusive(self.workspace):
            self.assertEqual(self.post(f'/api/leads/{lead}/organization',{'contact_status':'contacted'}).status_code,409)
        self.assertEqual(self.post(f'/api/leads/{lead}/organization',{'contact_status':'contacted'}).status_code,200)
        self.repo.create_search('busy','Cafe','Rio',10,workspace_id=self.workspace)
        self.assertEqual(self.post('/api/backups/export',{'password':password}).status_code,409)

    def test_restore_file_failure_rolls_back_database_and_session(self):
        lead=self.lead();self.repo.update_search('lead-search-'+str(self.workspace),status='completed')
        profile=Path(self.repo.database).parent/'whatsapp'/f'session-workspace-{self.workspace}'
        profile.mkdir(parents=True);(profile/'fixture.bin').write_bytes(b'original-session')
        service=self.app.extensions['backups'];password='backup-password-123'
        archive=service.export(self.workspace,password)
        self.post(f'/api/leads/{lead}/notes',{'body':'Added after backup'})
        user=1  # First account created by the isolated test fixture.
        preview=service.preview(self.workspace,user,archive,password)
        original_rename=Path.rename
        def failing_rename(path,target):
            if path.name.startswith('.restore-'):
                raise OSError('Fixture filesystem failure')
            return original_rename(path,target)
        with patch.object(Path,'rename',failing_rename):
            with self.assertRaises(BackupError):
                service.restore(self.workspace,user,preview['token'],password,'alice workspace')
        self.assertEqual(self.client.get(f'/api/leads/{lead}/dossier').json['notes'][0]['body'],'Added after backup')
        self.assertEqual((profile/'fixture.bin').read_bytes(),b'original-session')
        with self.repo.connection() as db:
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())


if __name__=='__main__':
    unittest.main()
