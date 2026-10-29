import tempfile
import threading
import time
import unittest
from pathlib import Path

from leadfinder import create_app
from leadfinder.integrations.whatsapp_runtime import DeliveryUncertain, IntegrationError
from leadfinder.models import Lead
from leadfinder.outreach import normalize_phone, render_message, validate_template, OutreachError


class FakeWhatsApp:
    def __init__(self):
        self.states = {}
        self.sent = []
        self.hook = None

    def status(self, workspace_id):
        return self.states.get(workspace_id,{'status':'disconnected','qr':None,'phone':None,'error':None})

    def connect(self, workspace_id, phone):
        self.states[workspace_id] = {'status':'ready','qr':None,'phone':phone,'error':None}
        return self.states[workspace_id]

    def disconnect(self, workspace_id):
        self.states.pop(workspace_id,None)

    def send(self, workspace_id, phone, body, sender_phone):
        self.sent.append((workspace_id,phone,body,sender_phone))
        if self.hook:
            return self.hook()
        return 'fake-message-'+str(len(self.sent))


class OutreachTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = FakeWhatsApp()
        self.app = create_app({'TESTING':True,'DATABASE':str(Path(self.temp.name)/'test.sqlite3')},whatsapp_provider=self.provider)
        self.repo = self.app.extensions['repository']
        self.store = self.app.extensions['outreach_store']
        self.client,self.workspace = self.make_account('alice')

    def tearDown(self):
        self.temp.cleanup()

    def make_account(self, username):
        accounts = self.app.extensions['accounts']
        user_id = accounts.create_user(username.title(),username,username+'@example.org','test-password-123')
        workspace_id = accounts.setup_workspace(user_id,username+' workspace')
        client = self.app.test_client()
        client.get('/login')
        with client.session_transaction() as session:
            token = session['csrf']
        self.assertEqual(client.post('/login',data={'csrf_token':token,'username':username,'password':'test-password-123'}).status_code,303)
        client.get('/')
        return client,workspace_id

    def post(self, path, data=None, client=None):
        client = client or self.client
        with client.session_transaction() as session:
            token = session['csrf']
        return client.post(path,json=data if data is not None else {},headers={'X-LeadFinder-Token':token})

    def template(self, body='Olá {{empresa}}, sou {{meu_nome}} do {{workspace}}.', name='Primeiro contato'):
        response = self.post('/api/messages',{'name':name,'body':body})
        self.assertEqual(response.status_code,201)
        return response.json['id']

    def connect(self):
        self.assertEqual(self.post('/api/integrations/whatsapp',{'name':'Alice','phone':'+55 21 99999-1111'}).status_code,200)
        self.assertEqual(self.post('/api/integrations/whatsapp/connect').status_code,202)

    def lead(self, identity='lead', phone='(21) 98888-2222', workspace=None):
        workspace = workspace or self.workspace
        search_id = identity+'-search-'+str(workspace)
        self.repo.create_search(search_id,'Cafe','Rio',10,workspace_id=workspace)
        self.repo.save_lead(search_id,Lead(identity,'Café '+identity,'https://example.org',phone=phone))
        return self.repo.list_leads(workspace_id=workspace)['items'][0]['id']

    def campaign(self, template_ids, simulated=True, target_ids=None, client=None):
        response = self.post('/api/campaigns',{'name':'Teste de disparo','simulated':simulated,'template_ids':template_ids,'target_ids':target_ids or [],'interval_seconds':3},client)
        self.assertEqual(response.status_code,201,response.json)
        return response.json['campaign']

    def wait(self, campaign_id, timeout=6):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            campaign = self.store.campaign(self.workspace,campaign_id)
            if campaign['status'] != 'running':
                return campaign
            time.sleep(.02)
        self.fail('Campaign worker timeout')

    def test_authenticated_integrations_and_csrf(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/api/messages').status_code,401)
        self.assertEqual(anonymous.get('/api/integrations/whatsapp').status_code,401)
        self.assertEqual(self.client.post('/api/messages',json={'name':'Test','body':'Hello'}).status_code,403)
        self.connect()
        state = self.client.get('/api/integrations/whatsapp').json
        self.assertEqual((state['status'],state['phone']),('ready','5521999991111'))
        self.assertEqual(self.post('/api/integrations/whatsapp',{'name':'Alice','phone':'(21) 98888-1111'}).status_code,400)
        self.assertEqual(self.post('/api/integrations/whatsapp/disconnect').status_code,200)
        self.assertEqual(self.client.get('/api/integrations/whatsapp').json['status'],'disconnected')

    def test_template_validation_edit_archive_and_safe_rendering(self):
        template_id = self.template()
        self.assertEqual(self.post('/api/messages',{'name':'Bad','body':'{{config.__class__}}'}).status_code,400)
        self.assertEqual(self.post('/api/messages',{'name':'Bad','body':'{{unknown}}'}).status_code,400)
        self.assertEqual(self.post('/api/messages',{'name':'Bad','body':'{{empresa'}).status_code,400)
        self.assertEqual(self.post('/api/messages/'+str(template_id),{'name':'Atualizado','body':'Oi {{nome}}'}).status_code,200)
        self.assertEqual(self.post(f'/api/messages/{template_id}/archive').status_code,200)
        self.assertEqual(self.client.get('/api/messages').json['items'],[])
        self.assertEqual(render_message('{{empresa}}',{'name':'<script>alert(1)</script>'},'Alice','Test'),'<script>alert(1)</script>')

    def test_workspace_isolation_for_all_resources(self):
        template_id = self.template()
        lead_id = self.lead()
        campaign = self.campaign([template_id])
        bob,bob_workspace = self.make_account('bob')
        self.assertEqual(bob.get('/api/messages').json['items'],[])
        self.assertEqual(self.post(f'/api/messages/{template_id}',{'name':'Attack','body':'Hello'},bob).status_code,404)
        self.assertEqual(self.post(f'/api/messages/{template_id}/archive',client=bob).status_code,404)
        self.assertEqual(bob.get('/api/campaigns/'+campaign['id']).status_code,404)
        self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/start',client=bob).status_code,404)
        self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/cancel',client=bob).status_code,404)
        self.assertEqual(bob.get('/api/outreach/targets').json['total'],0)
        self.assertEqual(self.post('/api/campaigns',{'name':'Attack','simulated':True,'template_ids':[template_id]},bob).status_code,400)
        self.post('/api/integrations/whatsapp',{'name':'Bob','phone':'+55 21 97777-1111'},bob)
        bob_template = self.post('/api/messages',{'name':'Bob template','body':'Hello'},bob).json['id']
        self.assertEqual(self.post('/api/campaigns',{'name':'Attack','simulated':False,'template_ids':[bob_template],'target_ids':[lead_id]},bob).status_code,400)
        self.assertEqual(self.client.get('/api/integrations/whatsapp').json['configured'],False)

    def test_fictional_client_never_calls_provider_without_integration(self):
        campaign = self.campaign([self.template()])
        self.assertIsNone(campaign['messages'][0]['phone'])
        self.assertIn('Café Horizonte (fictício)',campaign['messages'][0]['body'])
        self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/start').status_code,202)
        result = self.wait(campaign['id'])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['counts'],{'simulated':1})
        self.assertEqual(self.provider.sent,[])

    def test_fictional_phone_is_personalized_without_sending(self):
        template_id = self.template(body='Contato {{nome}}: {{telefone}}')
        payload = {'name':'Teste com telefone','simulated':True,'fictional_name':'Cliente de teste',
                   'fictional_phone':'(21) 98888-2222','template_ids':[template_id]}
        response = self.post('/api/campaigns',payload)
        self.assertEqual(response.status_code,201,response.json)
        campaign = response.json['campaign']
        self.assertEqual(campaign['messages'][0]['phone'],'5521988882222')
        self.assertEqual(campaign['messages'][0]['body'],'Contato Cliente de teste: 5521988882222')
        self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/start').status_code,202)
        self.assertEqual(self.wait(campaign['id'])['counts'],{'simulated':1})
        self.assertEqual(self.provider.sent,[])
        for value in ('123',123,None):
            payload['fictional_phone'] = value
            self.assertEqual(self.post('/api/campaigns',payload).status_code,400)

    def test_real_execution_requires_active_matching_account(self):
        self.post('/api/integrations/whatsapp',{'name':'Alice','phone':'+55 21 99999-1111'})
        campaign = self.campaign([self.template()],False,[self.lead()])
        self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/start').status_code,400)
        self.connect()
        self.provider.states[self.workspace]['phone']='5521000000000'
        self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/start').status_code,400)
        self.assertEqual(self.provider.sent,[])

    def test_real_test_number_requires_connection_and_records_events(self):
        template_id = self.template('Olá {{nome}}: {{telefone}}')
        payload = {'name':'Número de teste','simulated':False,'test_target':True,
                   'fictional_name':'Meu teste','fictional_phone':'+55 21 97777-3333','template_ids':[template_id]}
        self.assertEqual(self.post('/api/campaigns',payload).status_code,400)
        self.post('/api/integrations/whatsapp',{'name':'Alice','phone':'+55 21 99999-1111'})
        response = self.post('/api/campaigns',payload)
        self.assertEqual(response.status_code,201,response.json)
        campaign = response.json['campaign']
        self.assertTrue(campaign['test_target'])
        path='/api/campaigns/'+campaign['id']+'/start'
        self.assertEqual(self.post(path).status_code,400)
        self.assertIn('bloqueado',self.store.events(self.workspace,campaign['id'])[0]['message'])
        self.connect()
        self.assertEqual(self.post(path).status_code,202)
        result=self.wait(campaign['id'])
        self.assertEqual(result['counts'],{'sent':1})
        self.assertEqual(self.provider.sent[0][1],'5521977773333')
        self.assertTrue(result['messages'][0]['provider_id'])
        self.assertTrue(any('aceita pelo servidor' in event['message'] for event in result['events']))
        self.assertEqual(self.post('/api/campaigns',{**payload,'simulated':True}).status_code,400)
        self.assertEqual(self.post('/api/campaigns',{**payload,'fictional_phone':''}).status_code,400)

    def test_missing_provider_confirmation_never_completes(self):
        self.connect()
        self.provider.hook=lambda: None
        campaign=self.campaign([self.template()],False,[self.lead()])
        self.post('/api/campaigns/'+campaign['id']+'/start')
        result=self.wait(campaign['id'])
        self.assertEqual(result['status'],'paused')
        self.assertEqual(result['counts'],{'uncertain':1})
        self.assertTrue(any(event['level']=='error' for event in result['events']))

    def test_saved_enabled_connection_restores_after_server_restart(self):
        self.connect()
        provider=FakeWhatsApp()
        restarted=create_app({'TESTING':True,'DATABASE':self.repo.database},whatsapp_provider=provider)
        service=restarted.extensions['whatsapp_integration']
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and service.status(self.workspace)['status']!='ready':
            time.sleep(.02)
        self.assertEqual(service.status(self.workspace)['status'],'ready')
        self.assertEqual(provider.sent,[])
        self.assertTrue(any('Restaurando' in event['message'] for event in service.status(self.workspace)['events']))
        service.disconnect(self.workspace)
        provider2=FakeWhatsApp()
        create_app({'TESTING':True,'DATABASE':self.repo.database},whatsapp_provider=provider2)
        self.assertFalse(provider2.states)

    def test_snapshot_is_immutable_and_execution_is_idempotent(self):
        self.connect()
        template_id = self.template('Original {{empresa}}')
        campaign = self.campaign([template_id],False,[self.lead()])
        self.post('/api/messages/'+str(template_id),{'name':'Edited','body':'Changed text'})
        self.post(f'/api/messages/{template_id}/archive')
        self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/start').status_code,202)
        self.assertEqual(self.wait(campaign['id'])['counts'],{'sent':1})
        self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/start').status_code,400)
        self.assertEqual(len(self.provider.sent),1)
        self.assertIn('Original Café',self.provider.sent[0][2])

    def test_duplicate_and_invalid_numbers_are_reported(self):
        self.connect()
        first = self.lead('first','(21) 98888-2222')
        duplicate = self.lead('duplicate','+55 21 98888-2222')
        invalid = self.lead('invalid','98888-2222')
        result = self.post('/api/campaigns',{'name':'Numbers','simulated':False,'template_ids':[self.template()],'target_ids':[first,duplicate,invalid]})
        self.assertEqual(result.status_code,201)
        self.assertEqual(result.json['campaign']['target_count'],1)
        self.assertEqual(len(result.json['skipped']),2)

    def test_uncertain_delivery_pauses_without_retry(self):
        self.connect()
        campaign = self.campaign([self.template(),self.template('Outra mensagem','Segundo contato')],False,[self.lead()])
        def uncertain():
            raise DeliveryUncertain('Timeout durante envio',provider_id='fixture-pending-ack')
        self.provider.hook=uncertain
        self.post('/api/campaigns/'+campaign['id']+'/start')
        result = self.wait(campaign['id'])
        self.assertEqual(result['status'],'paused')
        self.assertEqual(result['counts'],{'pending':1,'uncertain':1})
        self.assertEqual(result['messages'][0]['provider_id'],'fixture-pending-ack')
        self.assertEqual(len(self.provider.sent),1)
        self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/start').status_code,400)

    def test_cancel_stops_remaining_messages_and_serializes_campaigns(self):
        self.connect()
        template_id = self.template()
        campaign = self.campaign([template_id,self.template('Sequence two','Second')],False,[self.lead()])
        second = self.campaign([template_id],False,[self.lead('second')])
        entered,release = threading.Event(),threading.Event()
        def blocking():
            entered.set();release.wait(4);return 'fake-message'
        self.provider.hook=blocking
        try:
            self.post('/api/campaigns/'+campaign['id']+'/start')
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.post('/api/campaigns/'+second['id']+'/start').status_code,400)
            self.assertEqual(self.post('/api/campaigns/'+campaign['id']+'/cancel').status_code,200)
        finally:
            release.set()
        result = self.wait(campaign['id'])
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(result['counts'],{'pending':1,'sent':1})
        self.assertEqual(len(self.provider.sent),1)

    def test_restart_marks_inflight_uncertain_without_resuming(self):
        campaign = self.campaign([self.template()])
        with self.repo.connection() as db:
            db.execute("UPDATE campaigns SET status='running' WHERE id=?",(campaign['id'],))
            db.execute("UPDATE campaign_messages SET status='sending' WHERE campaign_id=?",(campaign['id'],))
        self.store.recover()
        result = self.store.campaign(self.workspace,campaign['id'])
        self.assertEqual(result['status'],'interrupted')
        self.assertEqual(result['counts'],{'uncertain':1})
        self.assertEqual(self.provider.sent,[])


class PhoneTest(unittest.TestCase):
    def test_phone_normalization(self):
        self.assertEqual(normalize_phone('(21) 99999-1111'),'5521999991111')
        self.assertEqual(normalize_phone('+1 (202) 555-0123'),'12025550123')
        with self.assertRaises(OutreachError):
            normalize_phone('99999-1111')
