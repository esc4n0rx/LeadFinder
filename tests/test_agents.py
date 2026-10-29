"""Native tool execution, human confirmation, isolation and manual lead lifecycle."""
import copy
import io
import json
import zipfile
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import unittest
from unittest.mock import patch
from leadfinder.ai.catalog import AIError
from leadfinder.ai.agent import AgentService
from leadfinder.ai.agent_provider import AgentProvider
from leadfinder.ai.providers import AIProviders
from leadfinder.backups import seal,unseal
from leadfinder.models import Lead
from tests import test_ai as ai_helpers
from tests.test_ai import FakeAITransport

class NativeTransport(FakeAITransport):
    def __init__(self):
        super().__init__();self.queue=[]
    def request(self,method,url,headers,payload=None):
        if method=='GET':return super().request(method,url,headers,payload)
        self.calls.append((method,url,headers,copy.deepcopy(payload)))
        item=self.queue.pop(0) if self.queue else 'Pronto. Consulte as ações registradas.'
        if isinstance(item,Exception):raise item
        calls=item if isinstance(item,list) else []
        if '/responses' in url:
            return {'status':'completed','output':([{'type':'function_call','call_id':identity,'name':name,'arguments':json.dumps(args)} for identity,name,args in calls] if calls else [{'type':'message','content':[{'type':'output_text','text':item}]}]),'usage':{'input_tokens':2,'output_tokens':3}}
        if 'anthropic' in url:
            return {'stop_reason':'tool_use' if calls else 'end_turn','content':([{'type':'tool_use','id':identity,'name':name,'input':args} for identity,name,args in calls] if calls else [{'type':'text','text':item}])}
        return {'choices':[{'finish_reason':'tool_calls' if calls else 'stop','message':{'role':'assistant','content':None if calls else item,**({'tool_calls':[{'id':identity,'type':'function','function':{'name':name,'arguments':json.dumps(args)}} for identity,name,args in calls]} if calls else {})}}]}

class AgentsTest(unittest.TestCase):
    setUp=ai_helpers.AITest.setUp
    tearDown=ai_helpers.AITest.tearDown
    account=ai_helpers.AITest.account
    post=ai_helpers.AITest.post
    configure=ai_helpers.AITest.configure
    new_thread=ai_helpers.AITest.new_thread
    def native(self):
        transport=NativeTransport();self.service.providers=AIProviders(transport);self.configure();return transport
    def chat(self,thread=None,provider='openai',key=None,text='Crie as alterações que pedi.'):
        return self.post('/api/agents/threads/'+(thread or self.new_thread())+'/chat',{'provider':provider,'request_key':key or uuid4().hex,'message':text})
    def lead(self,identity='fixture',workspace=None):
        repo=self.app.extensions['repository'];workspace=workspace or self.workspace
        repo.create_search(identity,identity,'Rio',10,workspace_id=workspace)
        repo.save_lead(identity,Lead(identity,'Café '+identity,'https://example.org/maps',phone='21988882222',details={'description':'Original','attributes':['Acesso livre']}))
        repo.update_search(identity,status='completed')
        return repo.list_leads(workspace_id=workspace)['items'][0]['id']
    def test_native_protocols_create_resources_and_keep_previous_threads(self):
        transport=self.native()
        for provider in ('openai','claude','openrouter'):
            self.configure(provider)
            transport.queue=[[('call_'+provider,'messages_create',{'name':'Mensagem '+provider,'body':'Olá {{empresa}}! Podemos conversar?'})],'Mensagem criada.']
            response=self.chat(provider=provider)
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['status'],'completed',response.json)
            action=response.json['actions'][0];self.assertEqual(action['status'],'completed',action)
            self.assertTrue(action['result']['id'])
            payload=transport.calls[-1][3]
            if provider=='openai':self.assertTrue(any(i.get('type')=='function_call_output' for i in payload['input']))
            elif provider=='claude':self.assertEqual(payload['messages'][-1]['content'][0]['type'],'tool_result')
            else:self.assertEqual(payload['messages'][-1]['role'],'tool')
        self.assertEqual(len(self.client.get('/api/messages').json['items']),3)
        self.assertEqual(len(self.client.get('/api/ai/threads').json['items']),3)
    def test_actions_are_durable_deduplicated_and_http_retries_do_not_repeat(self):
        transport=self.native();thread=self.new_thread();key=uuid4().hex
        arguments={'name':'Novos clientes','body':'Olá {{empresa}}!'}
        transport.queue=[[('a','messages_create',arguments),('b','messages_create',arguments)],'Criado.']
        response=self.chat(thread,key=key);self.assertEqual(response.json['actions'][0]['status'],'completed',response.json)
        self.assertEqual(len(response.json['actions']),1)
        count=len(transport.calls)
        self.assertEqual(self.chat(thread,key=key).json['id'],response.json['id']);self.assertEqual(len(transport.calls),count)
        self.assertEqual(len(self.client.get('/api/messages').json['items']),1)
        self.assertEqual(self.chat(thread,key=key,text='Outro pedido').status_code,400)
    def test_real_actions_organize_leads_create_funnel_notes_and_context(self):
        transport=self.native();lead=self.lead()
        category=self.post('/api/categories',{'name':'Cafeterias'}).json['id']
        transport.queue=[[('a','leads_organize',{'ids':[lead],'changes':{'category_ids':[category],'stage':'demo'}}),('b','funnels_create',{'name':'Cafés em foco','category_id':category}),('c','notes_create',{'lead_id':lead,'body':'Cliente interessado'}),('d','product_context_set',{'product':'Agenda online'})],'Organização concluída.']
        result=self.chat().json;self.assertEqual([a['status'] for a in result['actions']],['completed']*4,result)
        funnel=self.client.get('/api/funnels').json['items'][0]
        board=self.client.get('/api/crm/board?funnel_id='+str(funnel['id'])).json
        self.assertEqual(next(c for c in board['columns'] if c['stage']=='demo')['total'],1)
        self.assertEqual(self.client.get('/api/crm/board/demo?funnel_id='+str(funnel['id'])+'&q=missing').json['total'],0)
        self.assertEqual(self.client.get('/api/leads/'+str(lead)+'/dossier').json['notes'][0]['body'],'Cliente interessado')
    def test_invalid_foreign_and_unknown_tools_are_visible_failures(self):
        transport=self.native();bob,workspace=self.account('other');foreign=self.lead('foreign',workspace)
        transport.queue=[[('a','leads_edit',{'id':foreign,'fields':{'name':'Inválido'}}),('b','messages_create',{'name':'Ataque','body':'x','workspace_id':workspace}),('c','shell_execute',{'command':'anything'})],'Não foi possível.']
        result=self.chat().json;self.assertEqual([a['status'] for a in result['actions']],['failed']*3,result)
        self.assertEqual(self.client.get('/api/messages').json['items'],[])
        self.assertEqual(bob.get('/api/leads/'+str(foreign)).json['name'],'Café foreign')
        self.assertEqual(self.post('/api/agents/threads/'+self.new_thread()+'/chat',{'provider':{},'request_key':uuid4().hex,'message':'test'}).status_code,400)
    def test_api_failure_keeps_successful_actions_and_never_retries(self):
        transport=self.native();transport.queue=[[('a','messages_create',{'name':'Primeira','body':'Olá!'})],AIError('API indisponível')]
        result=self.chat().json;self.assertEqual(result['status'],'failed');self.assertEqual(result['actions'][0]['status'],'completed')
        self.assertEqual(len(self.client.get('/api/messages').json['items']),1)
    def test_deletion_requires_review_scoping_freshness_and_is_idempotent(self):
        transport=self.native();lead=self.lead();transport.queue=[[('a','leads_delete',{'ids':[lead]})]]
        result=self.chat().json;action=result['actions'][0];self.assertEqual(action['status'],'pending',result)
        url='/api/agents/actions/'+action['id']
        self.assertEqual(self.client.get('/api/leads/'+str(lead)).status_code,200)
        self.assertEqual(self.post(url+'/confirm',{}).status_code,400)
        bob,_=self.account('other');self.assertEqual(bob.get(url+'/preview').status_code,400)
        self.assertEqual(self.post(url+'/confirm',{'confirmed':True},bob).status_code,400)
        self.post('/api/leads/'+str(lead)+'/edit',{'name':'Nome corrigido'})
        self.assertEqual(self.post(url+'/confirm',{'confirmed':True}).status_code,409)
        self.assertEqual(self.post(url+'/cancel').json['status'],'cancelled')
        transport.queue=[[('b','leads_delete',{'ids':[lead]})]];action=self.chat().json['actions'][0]
        url='/api/agents/actions/'+action['id']+'/confirm'
        self.assertEqual(self.post(url,{'confirmed':True}).json['status'],'completed')
        self.assertEqual(self.post(url,{'confirmed':True}).json['status'],'completed')
        self.assertEqual(self.client.get('/api/leads/'+str(lead)).status_code,404)
    def test_manual_edit_validation_preserves_source_dates_details_and_delete_cascades(self):
        lead=self.lead();before=self.client.get('/api/leads/'+str(lead)).json
        for bad in ({'workspace_id':99},{'website':'javascript:alert(1)'},{'rating':True},{'latitude':100},{'name':'x'}):
            self.assertEqual(self.post('/api/leads/'+str(lead)+'/edit',bad).status_code,400)
        bob,_=self.account('other');self.assertEqual(self.post('/api/leads/'+str(lead)+'/edit',{'name':'Nome'},bob).status_code,404)
        result=self.post('/api/leads/'+str(lead)+'/edit',{'name':'Nome corrigido','phone':'21999990000','description':'Atualizada','rating':4.8}).json
        for key in ('maps_url','first_seen_at','last_seen_at','identity'):self.assertEqual(result.get(key),before.get(key))
        self.assertEqual(result['details']['attributes'],['Acesso livre'])
        self.post('/api/leads/'+str(lead)+'/notes',{'body':'Anotação'})
        self.post('/api/leads/'+str(lead)+'/reminders',{'title':'Retornar','due_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        preview=self.post('/api/leads/delete-preview',{'ids':[lead]}).json
        self.assertEqual(self.post('/api/leads/delete',preview).status_code,400)
        result=self.post('/api/leads/delete',{**preview,'confirmed':True});self.assertEqual(result.status_code,200,result.json)
        with self.app.extensions['repository'].connection() as db:self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
    def test_restart_interrupts_execution_and_backup_restores_actions_as_inert(self):
        transport=self.native();lead=self.lead();category=self.post('/api/categories',{'name':'Segmento'}).json['id']
        self.post('/api/funnels',{'name':'Funil salvo','filters':{'category_id':category}})
        transport.queue=[[('a','leads_delete',{'ids':[lead]})]];action=self.chat().json['actions'][0]
        service=self.app.extensions['backups']
        # Completed searches only; snapshot does not need or open a WhatsApp session.
        raw=seal(service.snapshot(self.workspace),'backup-password-1234')
        preview=service.preview(self.workspace,1,raw,'backup-password-1234')
        service.restore(self.workspace,1,preview['token'],'backup-password-1234','aiuser workspace')
        with self.app.extensions['repository'].connection() as db:
            restored=dict(db.execute('SELECT * FROM ai_tool_calls').fetchone());self.assertEqual(restored['status'],'cancelled')
            funnel=dict(db.execute('SELECT * FROM lead_funnels').fetchone());cat=db.execute('SELECT id FROM lead_categories').fetchone()[0]
            self.assertEqual(json.loads(funnel['filters'])['category_id'],cat)
            db.execute("UPDATE ai_tool_calls SET status='executing'")
        AgentService(self.service,self.app.extensions['agent_service'].tools)
        with self.app.extensions['repository'].connection() as db:self.assertEqual(db.execute('SELECT status FROM ai_tool_calls').fetchone()[0],'interrupted')
    def test_legacy_backup_header_and_format_remain_supported(self):
        self.native();backup=self.app.extensions['backups'];raw=backup.snapshot(self.workspace)
        with zipfile.ZipFile(io.BytesIO(raw)) as source:
            files={name:source.read(name) for name in source.namelist()}
        packet=json.loads(files['workspace.json']);packet['format']=7
        packet['tables'].pop('ai_tool_calls');packet['tables'].pop('lead_funnels')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            for name,data in files.items():archive.writestr(name,json.dumps(packet) if name=='workspace.json' else data)
        legacy=seal(output.getvalue(),'backup-password-1234').replace(b'LEADFINDER8',b'LEADFINDER7',1)
        packet,_=backup.unpack(legacy,'backup-password-1234');self.assertEqual(packet['tables']['ai_tool_calls'],[])
    def test_routes_are_private_authenticated_and_csrf_protected(self):
        self.assertEqual(self.client.get('/agents').status_code,200)
        self.assertEqual(self.app.test_client().get('/agents').status_code,302)
        self.assertEqual(self.client.post('/api/leads/delete-preview',json={'ids':[1]}).status_code,403)
        self.assertNotIn('id="catalog-view"',self.client.get('/').get_data(as_text=True))
        self.assertNotIn('message-ai-tab',self.client.get('/messages').get_data(as_text=True))

    def prepare_real(self):
        self.post('/api/integrations/whatsapp',{'name':'Pessoa Teste','phone':'+5521999991111'})
        self.post('/api/integrations/whatsapp/connect')
        lead=self.lead();template=self.post('/api/messages',{'name':'Mensagem Teste','body':'Olá {{empresa}}!'}).json['id']
        return lead,template
    def test_campaign_tools_never_send_before_human_confirmation(self):
        transport=self.native();lead,template=self.prepare_real()
        transport.queue=[[('prepare','campaigns_prepare',{'name':'Disparo pelo agente','template_ids':[template],'target_ids':[lead]})],'Rascunho preparado.']
        result=self.chat().json;action=result['actions'][0];self.assertEqual(action['status'],'completed',result)
        campaign=action['result']['id'];wa=self.app.extensions['whatsapp_integration'].provider
        transport.queue=[[('start','campaigns_start',{'id':campaign})]]
        thread=self.new_thread();result=self.chat(thread).json;proposal=result['actions'][0]
        self.assertEqual(proposal['status'],'pending',result);self.assertEqual(wa.sent,[])
        # A later "sim" in chat cannot approve the durable proposal.
        transport.queue=['Use o botão de revisão para confirmar.'];self.chat(thread,text='sim')
        self.assertEqual(wa.sent,[])
        response=self.post('/api/agents/actions/'+proposal['id']+'/confirm',{'confirmed':True})
        self.assertEqual(response.json['status'],'completed',response.json)
        from tests.test_outreach import OutreachTest
        self.store=self.app.extensions['outreach_store'];OutreachTest.wait(self,campaign)
        self.assertEqual(len(wa.sent),1)
        self.post('/api/agents/actions/'+proposal['id']+'/confirm',{'confirmed':True})
        self.assertEqual(len(wa.sent),1)
    def test_pending_campaign_blocks_lead_deletion_and_expired_agenda_is_inert(self):
        transport=self.native();lead,template=self.prepare_real()
        response=self.post('/api/campaigns',{'name':'Preparado','simulated':False,'template_ids':[template],'target_ids':[lead]})
        campaign=response.json['campaign']['id']
        self.assertEqual(self.post('/api/leads/delete-preview',{'ids':[lead]}).status_code,409)
        due=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        transport.queue=[[('agenda','campaigns_schedule',{'id':campaign,'due_at':due})]]
        proposal=self.chat().json['actions'][0];self.assertEqual(proposal['status'],'pending',proposal)
        repo=self.app.extensions['repository']
        with repo.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM campaign_jobs').fetchone()[0],0)
            db.execute('UPDATE ai_tool_calls SET created_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),proposal['id']))
        self.assertEqual(self.post('/api/agents/actions/'+proposal['id']+'/confirm',{'confirmed':True}).status_code,400)
        with repo.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM campaign_jobs').fetchone()[0],0)
        self.assertEqual(self.app.extensions['whatsapp_integration'].provider.sent,[])
    def test_funnel_filters_remain_in_effect_on_all_pages_and_are_scoped(self):
        self.native();repo=self.app.extensions['repository']
        repo.create_search('many','Cafés','Rio',100,workspace_id=self.workspace)
        for index in range(30):repo.save_lead('many',Lead('lead-'+str(index),'Café '+str(index),'https://example.org',phone='21988882222'))
        repo.update_search('many',status='completed');self.lead('other')
        funnel=self.post('/api/funnels',{'name':'Só cafés numerados','filters':{'q':'Café ','only_phone':True}}).json
        response=self.client.get('/api/crm/board/new?funnel_id='+str(funnel['id'])+'&q=Caf%C3%A9%202&page=1').json
        self.assertTrue(response['items']);self.assertTrue(all(row['name'].startswith('Café 2') for row in response['items']))
        bob,_=self.account('other');self.assertEqual(bob.get('/api/crm/board?funnel_id='+str(funnel['id'])).status_code,404)
        self.assertEqual(self.client.get('/api/crm/board?funnel_id=invalid').status_code,400)

    def test_search_tools_reuse_postcode_radius_and_workspace_boundaries(self):
        from types import SimpleNamespace
        from leadfinder.geography import SearchArea
        transport=self.native();tools=self.app.extensions['agent_service'].tools
        resolved=[]
        tools.postcodes=SimpleNamespace(resolve=lambda code:(resolved.append(code) or SearchArea(code,'Irajá, Rio',-22.82,-43.32)))
        transport.queue=[[('search','searches_start',{'term':'Cafeterias','postcode':'21235-112','radius_km':3,'require_phone':True,'max_results':10})],'Busca iniciada.']
        with patch.object(tools.search,'start',return_value={'id':'fixture','status':'queued'}) as start:
            result=self.chat().json;self.assertEqual(result['actions'][0]['status'],'completed',result)
            self.assertEqual(resolved,['21235112']);self.assertEqual(start.call_args.kwargs['workspace_id'],self.workspace)
            self.assertEqual(start.call_args.kwargs['area'].radius_km,3);self.assertTrue(start.call_args.kwargs['require_phone'])
        transport.queue=[[('invalid','searches_start',{'term':'Cafeterias','radius_km':100})],'Confira o raio.']
        with patch.object(tools.search,'start') as start:
            result=self.chat().json;self.assertEqual(result['actions'][0]['status'],'failed');start.assert_not_called()

if __name__=='__main__':unittest.main()
