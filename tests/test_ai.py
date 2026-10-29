import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

from leadfinder import create_app
from leadfinder.ai.catalog import AIError
from leadfinder.ai.providers import AIProviders, JsonTransport
from leadfinder.ai.service import parse_reply
from tests.test_outreach import FakeWhatsApp


class FakeAITransport:
    def __init__(self):
        self.calls=[]
        self.error=None
        self.hook=None
        self.reply={'reply':'Vamos destacar o benefício e um CTA simples.','messages':[
            {'name':'Primeiro contato','body':'Olá {{empresa}}! Oferecemos agendamento online. Podemos conversar por 15 minutos?'}]}

    def request(self, method, url, headers, payload=None):
        self.calls.append((method,url,headers,payload))
        if self.error:
            raise AIError(self.error)
        if method=='GET' and url.endswith('/key'):
            return {'data':{'label':'Test key','is_free_tier':False}}
        if method=='GET':
            return {'data':[{'id':identity} for identity in ['gpt-6.1-terra','gpt-6.1-sol','openai/gpt-6.1-terra','claude-sonnet-5-5','text-embedding-3-large']]}
        if self.hook:
            self.hook()
        content=json.dumps(self.reply,ensure_ascii=False)
        if '/responses' in url:
            return {'status':'completed','output':[{'type':'reasoning'},{'type':'message','content':[{'type':'output_text','text':content}]}],
                    'usage':{'input_tokens':21,'output_tokens':45,'secret':'not exposed'}}
        if 'anthropic.com' in url:
            return {'content':[{'type':'thinking','thinking':'not exposed'},{'type':'text','text':content}],
                    'stop_reason':'end_turn','usage':{'input_tokens':12,'output_tokens':40}}
        return {'choices':[{'message':{'content':content},'finish_reason':'stop'}],'usage':{'prompt_tokens':30,'completion_tokens':50}}


class AITest(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.transport=FakeAITransport()
        self.app=create_app({'TESTING':True,'DATABASE':str(Path(self.directory.name)/'test.sqlite3')},
            whatsapp_provider=FakeWhatsApp(),ai_provider=AIProviders(self.transport))
        self.service=self.app.extensions['ai_service']
        self.client,self.workspace=self.account('aiuser')

    def tearDown(self):
        self.directory.cleanup()

    def account(self, username):
        accounts=self.app.extensions['accounts']
        identity=accounts.create_user(username,username,username+'@example.org','test-password-123')
        workspace=accounts.setup_workspace(identity,username+' workspace')
        client=self.app.test_client()
        client.get('/login')
        with client.session_transaction() as session:
            token=session['csrf']
        client.post('/login',data={'csrf_token':token,'username':username,'password':'test-password-123'})
        client.get('/')
        return client,workspace

    def post(self, path, data=None, client=None):
        client=client or self.client
        with client.session_transaction() as session:
            token=session['csrf']
        return client.post(path,json=data or {},headers={'X-LeadFinder-Token':token})

    def configure(self, provider='openai', client=None):
        model={'openai':'gpt-6.1-terra','openrouter':'openai/gpt-6.1-terra','claude':'claude-sonnet-5-5'}[provider]
        result=self.post('/api/integrations/ai/'+provider,{'api_key':'fake-api-key-for-tests-123456','model':model},client)
        self.assertEqual(result.status_code,200,result.json)
        return result

    def new_thread(self):
        return self.post('/api/ai/threads').json['id']

    def test_auth_csrf_and_no_network_on_configuration_read(self):
        self.assertEqual(self.app.test_client().get('/api/integrations/ai').status_code,401)
        self.assertEqual(self.client.post('/api/integrations/ai/openai',json={}).status_code,403)
        configs=self.client.get('/api/integrations/ai').json['providers']
        self.assertEqual(len(configs),3)
        self.assertFalse(any(item['configured'] for item in configs))
        self.assertFalse(self.transport.calls)
        self.assertEqual(self.client.get('/profile/integrations/ai').status_code,200)

    def test_credentials_encrypted_scoped_and_replace_remove(self):
        self.configure()
        row=self.service.config(self.workspace,'openai')
        self.assertNotIn('fake-api-key',row['encrypted_key'])
        self.assertEqual(self.service.vault.decrypt(row['encrypted_key']),'fake-api-key-for-tests-123456')
        response=self.client.get('/api/integrations/ai').get_data(as_text=True)
        self.assertNotIn('fake-api-key',response)
        self.assertNotIn('encrypted_key',response)
        other,workspace=self.account('otherai')
        self.assertFalse(other.get('/api/integrations/ai').json['providers'][0]['configured'])
        self.assertEqual(self.post('/api/integrations/ai/openai/test',client=other).status_code,400)
        updated=self.post('/api/integrations/ai/openai',{'api_key':'','model':'gpt-6.1-sol'})
        self.assertEqual(updated.status_code,200)
        self.assertEqual(self.service.config(self.workspace,'openai')['encrypted_key'],row['encrypted_key'])
        self.post('/api/integrations/ai/openai/remove')
        self.assertIsNone(self.service.config(self.workspace,'openai'))

    def test_invalid_settings_and_missing_encryption_key(self):
        self.assertEqual(self.post('/api/integrations/ai/unknown',{'api_key':'fake'}).status_code,400)
        self.assertEqual(self.post('/api/integrations/ai/openai',{'api_key':'too short'}).status_code,400)
        self.assertEqual(self.post('/api/integrations/ai/openai',{'api_key':'fake-api-key-123456','model':'https://evil.test'}).status_code,400)
        self.configure()
        self.service.vault.path.unlink()
        self.assertEqual(self.post('/api/integrations/ai/openai/test').status_code,400)
        self.assertFalse(self.service.vault.path.exists())
        self.assertEqual(self.post('/api/integrations/ai/claude',{'api_key':'fake-api-key-123456'}).status_code,400)
        self.assertFalse(self.service.vault.path.exists())

    def test_live_catalog_and_test_are_read_only(self):
        self.configure()
        result=self.client.get('/api/integrations/ai/openai/models')
        self.assertEqual(result.status_code,200)
        self.assertNotIn('text-embedding-3-large',[item['id'] for item in result.json['models']])
        self.assertTrue(self.post('/api/integrations/ai/openai/test').json['ok'])
        self.assertTrue(all(call[0]=='GET' for call in self.transport.calls))

    def test_openrouter_checks_authenticated_key_before_public_catalog(self):
        self.configure('openrouter')
        self.assertTrue(self.post('/api/integrations/ai/openrouter/test').json['ok'])
        self.assertTrue(self.transport.calls[0][1].endswith('/key'))
        self.assertTrue(self.transport.calls[1][1].endswith('/models'))
        self.assertTrue(all(call[0]=='GET' for call in self.transport.calls))
        self.transport.error='Chave de API inválida ou expirada.'
        self.assertEqual(self.post('/api/integrations/ai/openrouter/test').status_code,400)

    def test_all_provider_contracts_and_explicit_template_review(self):
        for provider in ('openai','claude','openrouter'):
            with self.subTest(provider=provider):
                self.configure(provider)
                thread=self.new_thread()
                payload={'provider':provider,'message':'Vendo agendamento online para clínicas. Quero um CTA para uma conversa.','request_key':uuid4().hex}
                result=self.post('/api/ai/threads/'+thread+'/chat',payload)
                self.assertEqual(result.status_code,200,result.json)
                self.assertEqual(result.json['status'],'completed')
                self.assertEqual(result.json['suggestions'][0]['name'],'Primeiro contato')
                self.assertEqual(self.app.extensions['outreach_store'].templates(self.workspace),[])
                method,url,headers,body=self.transport.calls[-1]
                self.assertEqual(headers['Authorization'],'Bearer fake-api-key-for-tests-123456')
                if provider=='openai':
                    self.assertTrue(url.endswith('/responses'))
                    self.assertFalse(body['store'])
                    self.assertEqual(body['text']['format']['type'],'json_schema')
                elif provider=='claude':
                    self.assertEqual(headers['anthropic-version'],'2026-10-21')
                    self.assertIn('system',body)
                else:
                    self.assertTrue(url.endswith('/chat/completions'))
                    self.assertEqual(body['messages'][0]['role'],'system')

    def test_history_idempotency_and_workspace_isolation(self):
        self.configure()
        thread=self.new_thread();path='/api/ai/threads/'+thread+'/chat'
        payload={'provider':'openai','message':'Primeiro contexto da minha campanha','request_key':uuid4().hex}
        first=self.post(path,payload).json
        self.assertEqual(self.post(path,payload).json['id'],first['id'])
        self.assertEqual(len([call for call in self.transport.calls if call[0]=='POST']),1)
        self.post(path,{'provider':'openai','message':'Agora refine o CTA','request_key':uuid4().hex})
        self.assertEqual([message['role'] for message in self.transport.calls[-1][3]['input']],['user','assistant','user'])
        other,_=self.account('isolation')
        self.assertEqual(other.get('/api/ai/threads/'+thread).status_code,400)
        self.assertEqual(other.get('/api/ai/threads').json['items'],[])
        self.assertEqual(self.post(path,payload,other).status_code,400)
        self.assertEqual(self.post(path,{**payload,'message':'Different request'}).status_code,400)

    def test_errors_are_visible_and_not_retried(self):
        self.configure();thread=self.new_thread()
        self.transport.error='Créditos insuficientes no provedor.'
        payload={'provider':'openai','message':'Gere uma mensagem','request_key':uuid4().hex}
        path='/api/ai/threads/'+thread+'/chat'
        result=self.post(path,payload).json
        self.assertEqual(result['status'],'failed')
        self.assertIn('Créditos',result['error'])
        self.assertEqual(self.post(path,payload).json['id'],result['id'])
        self.assertEqual(len(self.transport.calls),1)

    def test_restart_preserves_credentials_and_conversation(self):
        self.configure();identity=self.new_thread()
        self.post('/api/ai/threads/'+identity+'/chat',{'provider':'openai','message':'Campanha persistida','request_key':uuid4().hex})
        from leadfinder.ai.service import AIService
        restored=AIService(self.service.repo,AIProviders(self.transport))
        self.assertEqual(restored.thread(self.workspace,identity)['turns'][0]['user_text'],'Campanha persistida')
        self.assertTrue(restored.test(self.workspace,'openai')['ok'])
        self.assertNotIn(b'fake-api-key-for-tests-123456',Path(self.service.repo.database).read_bytes())
        self.assertEqual(self.post('/api/ai/threads/'+identity+'/chat',{'provider':[],'message':'Invalid','request_key':uuid4().hex}).status_code,400)

    def test_one_generation_per_workspace_and_recovery(self):
        self.configure();thread=self.new_thread();other_thread=self.new_thread()
        entered,release=threading.Event(),threading.Event()
        self.transport.hook=lambda:(entered.set(),release.wait(5))
        payload={'provider':'openai','message':'Contexto','request_key':uuid4().hex}
        runner=threading.Thread(target=lambda:self.service.chat(self.workspace,thread,payload))
        runner.start()
        try:
            self.assertTrue(entered.wait(4))
            with self.assertRaises(AIError):
                self.service.chat(self.workspace,other_thread,{**payload,'request_key':uuid4().hex})
        finally:
            release.set();runner.join(6)
        with self.service.repo.connection() as db:
            db.execute("UPDATE ai_turns SET status='pending' WHERE thread_id=?",(thread,))
        from leadfinder.ai.service import AIService
        recovered=AIService(self.service.repo,AIProviders(self.transport))
        self.assertEqual(recovered.thread(self.workspace,thread)['turns'][0]['status'],'failed')


class AIParsingTest(unittest.TestCase):
    def test_plain_text_refusal_and_template_validation(self):
        reply,suggestions,warning=parse_reply('<script>alert(1)</script>')
        self.assertEqual(suggestions,[])
        self.assertTrue(warning)
        with self.assertRaises(AIError):
            parse_reply(json.dumps({'reply':'Ok','messages':[{'name':'Teste','body':'Olá {{unknown}}'}]}))
        with self.assertRaises(AIError):
            parse_reply('{}')

    def test_http_errors_do_not_echo_provider_body_or_secret(self):
        from io import BytesIO
        error=HTTPError('https://api.openai.com/v1/responses',401,'invalid',{},BytesIO(b'echoed-secret-value'))
        with patch('leadfinder.ai.providers.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(AIError) as caught:
                JsonTransport().request('POST','https://api.openai.com/v1/responses',{}, {})
            self.assertNotIn('echoed-secret',str(caught.exception))
