"""Workspace isolation, durable grouping, migration, and honest contact states."""
import time
import unittest
from pathlib import Path

from leadfinder.lead_directory import record_outgoing
from leadfinder.models import Lead
from tests import test_outreach as helpers


class DirectoryTest(unittest.TestCase):
    setUp=helpers.OutreachTest.setUp
    tearDown=helpers.OutreachTest.tearDown
    make_account=helpers.OutreachTest.make_account
    post=helpers.OutreachTest.post
    connect=helpers.OutreachTest.connect
    lead=helpers.OutreachTest.lead
    template=helpers.OutreachTest.template
    campaign=helpers.OutreachTest.campaign
    wait=helpers.OutreachTest.wait

    def category(self,name='Restaurantes',client=None):
        response=self.post('/api/categories',{'name':name},client)
        self.assertEqual(response.status_code,201,response.json)
        return response.json['id']

    def test_categories_crud_validation_and_workspace_boundaries(self):
        self.assertEqual(self.app.test_client().get('/api/categories').status_code,401)
        self.assertEqual(self.client.post('/api/categories',json={'name':'No CSRF'}).status_code,403)
        category=self.category()
        self.assertEqual(self.post('/api/categories',{'name':'restaurantes'}).status_code,400)
        for value in ('',None,12,'a'*61):
            self.assertEqual(self.post('/api/categories',{'name':value}).status_code,400)
        bob,_=self.make_account('bob')
        self.assertEqual(bob.get('/api/categories').json['items'],[])
        self.assertEqual(self.post(f'/api/categories/{category}',{'name':'Ataque'},bob).status_code,404)
        self.assertEqual(self.post(f'/api/categories/{category}/delete',client=bob).status_code,404)
        self.assertEqual(self.post(f'/api/categories/{category}',{'name':'Alimentação'}).status_code,200)
        self.assertEqual(self.client.get('/api/categories').json['items'][0]['name'],'Alimentação')

    def test_search_assigns_category_without_overwriting_maps_or_previous_groups(self):
        first=self.category('Prioridade A');second=self.category('Prioridade B')
        lead=Lead('cafe','Café Exemplo','https://example.org',category='Cafeteria',phone='(21) 98888-2222')
        for index,category in enumerate([first,second,first]):
            self.repo.create_search(str(index),'Cafe','Rio',10,workspace_id=self.workspace,category_id=category)
            self.repo.save_lead(str(index),lead)
        item=self.repo.list_leads(workspace_id=self.workspace)['items'][0]
        self.assertEqual(item['category'],'Cafeteria')
        self.assertEqual([c['id'] for c in item['categories']],[first,second])
        self.assertEqual(self.client.get('/api/categories').json['items'][0]['lead_count'],1)
        self.assertEqual(self.post(f'/api/categories/{first}/delete').status_code,200)
        item=self.repo.get_lead(item['id'],self.workspace)
        self.assertEqual([c['id'] for c in item['categories']],[second])
        self.assertIsNone(self.repo.get_search('0',self.workspace)['lead_category_id'])
        # A running collector can continue saving after its category is deleted.
        self.repo.save_lead('0',lead)
        self.assertEqual(self.repo.stats(self.workspace)['total'],1)

    def test_organization_filter_pagination_and_atomic_validation(self):
        category=self.category();lead_id=self.lead()
        path=f'/api/leads/{lead_id}/organization'
        self.assertEqual(self.post(path,{'category_ids':[category],'contact_status':'conversed'}).status_code,200)
        data=self.client.get(f'/api/leads?category_id={category}&contact_status=conversed&grouped=true').json
        self.assertEqual(data['total'],1)
        self.assertEqual(data['items'][0]['contact_status'],'conversed')
        self.assertEqual(self.client.get('/api/leads?category_id=0').json['total'],0)
        self.assertEqual(self.client.get('/api/leads?contact_status=new').json['total'],0)
        bob,_=self.make_account('bob');foreign=self.category('Outra',bob)
        self.assertEqual(self.post(path,{'category_ids':[foreign],'contact_status':'new'}).status_code,400)
        self.assertEqual(self.repo.get_lead(lead_id,self.workspace)['contact_status'],'conversed')
        self.assertEqual(self.post(path,{'contact_status':'new'},bob).status_code,404)
        for payload in ({'category_ids':[True]},{'category_ids':None},{'category_ids':[category,category]},
                        {'contact_status':'invalid'},{'contact_status':[]},{'name':'Unsupported'}):
            self.assertEqual(self.post(path,payload).status_code,400)
        self.assertEqual(self.post(path,{'category_ids':[]}).status_code,200)
        self.assertEqual(self.client.get('/api/leads?category_id=0').json['total'],1)
        for query in ('category_id=-1','category_id=abc','category_id='+('1'*15),'contact_status=invalid','page=0'):
            self.assertEqual(self.client.get('/api/leads?'+query).status_code,400)

    def test_search_http_validation_and_collection_category(self):
        category=self.category()
        class Collector:
            def collect(self,term,location,limit,on_lead,*args):
                on_lead(Lead('collected','Café Coletado','https://example.org',phone='21988882222'))
        self.app.extensions['search_service'].collector_factory=Collector
        bob,_=self.make_account('bob');foreign=self.category('Outro workspace',bob)
        for value in (True,0,'1',foreign):
            self.assertEqual(self.post('/api/searches',{'term':'Cafe','category_id':value}).status_code,400)
        response=self.post('/api/searches',{'term':'Cafe','category_id':category})
        self.assertEqual(response.status_code,202,response.json)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and self.repo.get_search(response.json['id'])['status'] in ('running','queued'):
            time.sleep(.02)
        item=self.repo.list_leads(workspace_id=self.workspace)['items'][0]
        self.assertEqual(item['categories'][0]['id'],category)

    def test_real_send_starts_contact_but_never_marks_conversation(self):
        self.connect();lead_id=self.lead()
        campaign=self.campaign([self.template()],False,[lead_id])
        self.post('/api/campaigns/'+campaign['id']+'/start')
        self.assertEqual(self.wait(campaign['id'])['counts'],{'sent':1})
        self.assertEqual(self.repo.get_lead(lead_id,self.workspace)['contact_status'],'contacted')
        self.post(f'/api/leads/{lead_id}/organization',{'contact_status':'conversed'})
        with self.repo.connection() as db:
            record_outgoing(db,self.workspace,'5521988882222')
        self.assertEqual(self.repo.get_lead(lead_id,self.workspace)['contact_status'],'conversed')
        bob,bob_workspace=self.make_account('bob')
        other=self.lead(workspace=bob_workspace)
        self.assertEqual(self.repo.get_lead(other,bob_workspace)['contact_status'],'new')

    def test_uncertain_and_fictional_tests_do_not_mark_real_leads_contacted(self):
        from leadfinder.integrations.whatsapp_runtime import DeliveryUncertain
        self.connect();lead_id=self.lead()
        def uncertain():
            raise DeliveryUncertain('Sem confirmação')
        self.provider.hook=uncertain
        campaign=self.campaign([self.template()],False,[lead_id])
        self.post('/api/campaigns/'+campaign['id']+'/start');self.wait(campaign['id'])
        self.assertEqual(self.repo.get_lead(lead_id,self.workspace)['contact_status'],'new')
        self.provider.hook=None
        response=self.post('/api/campaigns',{'name':'Teste fictício','simulated':False,'test_target':True,
            'fictional_phone':'21988882222','template_ids':[self.template()]})
        self.assertEqual(response.status_code,201,response.json)
        campaign=response.json['campaign'];self.post('/api/campaigns/'+campaign['id']+'/start');self.wait(campaign['id'])
        self.assertEqual(self.repo.get_lead(lead_id,self.workspace)['contact_status'],'new')

    def test_v5_upgrade_preserves_existing_leads_and_backfills_real_contact_only(self):
        self.connect();lead_id=self.lead()
        campaign=self.campaign([self.template()],False,[lead_id])
        self.post('/api/campaigns/'+campaign['id']+'/start');self.wait(campaign['id'])
        # Recreate the exact pre-feature schema in this disposable database.
        with self.repo.connection() as db:
            for table in ('ai_tool_calls','lead_funnels','campaign_jobs','product_context','reminders','lead_events','lead_notes','lead_profiles'):
                db.execute('DROP TABLE '+table)
            db.execute('ALTER TABLE ai_turns DROP COLUMN context_snapshot')
            for column in ('scheduled_at','next_send_at','pause_requested'):
                db.execute('ALTER TABLE campaigns DROP COLUMN '+column)
            db.execute('ALTER TABLE searches DROP COLUMN lead_category_id')
            db.execute('DROP TABLE lead_category_links');db.execute('DROP TABLE lead_contacts')
            db.execute('DROP TABLE lead_categories');db.execute('DROP INDEX idx_lead_workspace_id')
            db.execute('PRAGMA user_version=5')
        self.repo.initialize()
        item=self.repo.get_lead(lead_id,self.workspace)
        self.assertEqual(item['contact_status'],'contacted');self.assertEqual(item['categories'],[])
        self.assertTrue(Path(self.repo.database+'.before-categories-backup.sqlite3').exists())
        with self.repo.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],8)
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
        self.repo.initialize()
        self.assertEqual(self.repo.stats(self.workspace)['total'],1)


if __name__=='__main__':
    unittest.main()
