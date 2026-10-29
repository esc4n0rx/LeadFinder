import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from leadfinder import create_app
from leadfinder.geography import GeographyError, PostcodeResolver, SearchArea, distance_km
from leadfinder.models import Lead
from leadfinder.repository import Repository


class FakeResolver:
    def resolve(self, postcode):
        if postcode != '21235112':
            raise GeographyError('CEP não encontrado.')
        return SearchArea(postcode, 'Irajá, Rio de Janeiro, RJ', -22.8366, -43.3252)


class PlaceCollector:
    seen = []
    places = []

    def collect(self, term, location, limit, on_lead, on_error, progress, check_cancel, area=None):
        self.seen.append({'limit': limit, 'area': area})
        progress(found=len(self.places))
        for lead in self.places:
            on_lead(lead)


class Phase2Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {'TESTING': True, 'DATABASE': str(Path(self.temp.name)/'app.sqlite3')}
        PlaceCollector.seen, PlaceCollector.places = [], []
        self.app = create_app(self.config, collector_factory=PlaceCollector, postcode_resolver=FakeResolver())
        self.repo = self.app.extensions['repository']
        self.store = self.app.extensions['accounts']
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self, client=None):
        client = client or self.client
        with client.session_transaction() as session:
            return session['csrf']

    def register(self, username='alice', setup=True, client=None):
        client = client or self.client
        client.get('/register')
        response = client.post('/register', data={'csrf_token': self.csrf(client), 'name': 'Alice Example', 'username': username,
            'email': username+'@example.org', 'password': 'correct-horse-123', 'password_confirmation': 'correct-horse-123'})
        self.assertEqual(response.status_code, 303)
        client.get('/setup')
        if setup:
            self.assertEqual(client.post('/setup', data={'csrf_token':self.csrf(client), 'workspace_name':username+' Workspace'}).status_code, 303)
            client.get('/')
        return self.store.find_username(username)

    def post_api(self, data, client=None):
        client = client or self.client
        return client.post('/api/searches', json=data, headers={'X-LeadFinder-Token':self.csrf(client)})

    def wait(self, search_id):
        for _ in range(300):
            search = self.repo.get_search(search_id)
            if search['status'] not in ('queued','running'):
                return search
            time.sleep(.01)
        self.fail('Worker timeout')

    def logout(self, client=None):
        client = client or self.client
        return client.post('/logout', data={'csrf_token': self.csrf(client)})

    def test_anonymous_authentication_and_setup_guards(self):
        self.assertEqual(self.client.get('/').location, '/welcome')
        self.assertEqual(self.client.get('/api/overview').status_code, 401)
        self.assertEqual(self.client.get('/welcome').status_code, 200)
        user = self.register(setup=False)
        self.assertNotIn('correct-horse', user['password_hash'])
        self.assertTrue(user['password_hash'].startswith('scrypt:'))
        self.assertEqual(self.client.get('/').location, '/setup')
        self.assertEqual(self.client.get('/api/overview').status_code, 403)
        self.assertEqual(self.post_api({'term':'Cafe'}).status_code, 403)
        self.assertEqual(self.client.post('/setup', data={'csrf_token':self.csrf(),'workspace_name':'A'}).status_code, 400)

    def test_logout_revokes_cookie_and_login_is_case_insensitive(self):
        self.register()
        cookie = self.client.get_cookie('leadfinder_auth')
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, 'Lax')
        self.assertEqual(self.logout().status_code, 303)
        self.client.set_cookie('leadfinder_auth', cookie.value)
        self.assertEqual(self.client.get('/api/overview').status_code, 401)
        self.client.get('/login')
        response = self.client.post('/login', data={'csrf_token':self.csrf(), 'username':'ALICE','password':'correct-horse-123'})
        self.assertEqual(response.location, '/')
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertNotEqual(self.client.get_cookie('leadfinder_auth').value, cookie.value)

    def test_csrf_and_duplicate_identity(self):
        self.register()
        self.assertEqual(self.client.post('/logout').status_code, 403)
        self.assertEqual(self.client.get('/api/overview').status_code, 200)
        self.logout()
        self.client.get('/register')
        response = self.client.post('/register', data={'csrf_token':self.csrf(),'name':'Other Name','username':'ALICE','email':'other@example.org', 'password':'correct-horse-123','password_confirmation':'correct-horse-123'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('já está cadastrado', response.text)

    def test_profile_password_verification_rotation_and_session_persistence(self):
        self.register()
        old_cookie = self.client.get_cookie('leadfinder_auth').value
        data = {'csrf_token':self.csrf(),'name':'Alice Updated','username':'alice.updated','email':'updated@example.org','current_password':'wrong'}
        self.assertEqual(self.client.post('/profile',data=data).status_code,400)
        self.assertEqual(self.store.get_user(1)['username'],'alice')
        data.update(current_password='correct-horse-123',new_password='new-password-456',password_confirmation='new-password-456')
        self.assertEqual(self.client.post('/profile', data=data).status_code,303)
        self.assertEqual(self.store.get_user(1)['username'],'alice.updated')
        self.assertIsNone(self.store.session_user(old_cookie))
        self.client.get('/profile')
        current_cookie = self.client.get_cookie('leadfinder_auth').value
        other_app = create_app(self.config, collector_factory=PlaceCollector, postcode_resolver=FakeResolver())
        other = other_app.test_client()
        other.set_cookie('leadfinder_auth', current_cookie)
        self.assertEqual(other.get('/api/overview').status_code,200)
        self.logout()
        self.client.get('/login')
        self.assertEqual(self.client.post('/login',data={'csrf_token':self.csrf(),'username':'alice.updated','password':'new-password-456'}).status_code,303)

    def test_workspace_isolation_and_cross_workspace_mutation(self):
        alice = self.register()
        workspace_a = self.store.workspace(alice['id'])['id']
        bob_client = self.app.test_client()
        bob = self.register('bob', client=bob_client)
        workspace_b = self.store.workspace(bob['id'])['id']
        self.repo.create_search('alice-search','Cafe','Rio',10,workspace_id=workspace_a)
        self.repo.save_lead('alice-search',Lead('same-place','Alice private record','https://example.org',phone='21999990001'))
        alice_lead = self.repo.list_leads(workspace_id=workspace_a)['items'][0]
        self.assertEqual(bob_client.get('/api/overview').json['stats']['total'],0)
        self.assertEqual(bob_client.get('/api/leads?search_id=alice-search').json['total'],0)
        self.assertEqual(bob_client.get(f'/api/leads/{alice_lead["id"]}').status_code,404)
        self.assertEqual(bob_client.post('/api/searches/alice-search/cancel',json={},headers={'X-LeadFinder-Token':self.csrf(bob_client)}).status_code,404)
        self.repo.create_search('bob-search','Cafe','Rio',10,workspace_id=workspace_b)
        self.repo.save_lead('bob-search',Lead('same-place','Bob separate record','https://example.org',phone='21999990002'))
        self.assertEqual(self.repo.list_leads(workspace_id=workspace_a)['items'][0]['phone'],'21999990001')
        self.assertEqual(self.repo.list_leads(workspace_id=workspace_b)['items'][0]['phone'],'21999990002')

    def test_cep_radius_phone_and_missing_coordinates_filters(self):
        self.register()
        PlaceCollector.places = [
            Lead('no-phone','No phone','https://example.org',latitude=-22.8366,longitude=-43.3252),
            Lead('far','Outside','https://example.org',phone='21999990000',latitude=-23.5,longitude=-43.3252),
            Lead('unknown','No coordinates','https://example.org',phone='21999990000'),
            Lead('near','Inside','https://example.org',phone='21999990000',latitude=-22.837,longitude=-43.3252),
        ]
        response = self.post_api({'term':'Cafe','postcode':'21235-112','radius_km':1,'max_results':10})
        self.assertEqual(response.status_code,202)
        result = self.wait(response.json['id'])
        self.assertEqual((result['saved'],result['processed'],result['skipped_phone'],result['skipped_distance'],result['skipped_coordinates']),(1,4,1,1,1))
        self.assertEqual(result['postcode'],'21235112')
        self.assertIn('1 com telefone não encontrado',result['message'])
        self.assertIn('1 fora do raio',result['message'])
        self.assertIn('1 sem coordenadas',result['message'])
        self.assertEqual(self.client.get('/api/leads').json['items'][0]['name'],'Inside')
        self.assertEqual(PlaceCollector.seen[0]['area'].radius_km,1)
        self.assertGreaterEqual(PlaceCollector.seen[0]['limit'],100)

    def test_saved_limit_counts_accepted_places_and_phone_filter_opt_out(self):
        self.register()
        PlaceCollector.places = [Lead('a','No phone','https://example.org'),Lead('b','With phone','https://example.org',phone='21999990000'),Lead('c','More','https://example.org',phone='21999990000')]
        result = self.wait(self.post_api({'term':'Cafe','max_results':1}).json['id'])
        self.assertEqual((result['saved'],result['skipped_phone'],result['processed']),(1,1,2))
        result = self.wait(self.post_api({'term':'Cafe','max_results':1,'require_phone':False}).json['id'])
        self.assertEqual(result['saved'],1)
        self.assertEqual(self.client.get('/api/leads?only_phone=true').json['total'],1)
        self.assertEqual(self.client.get('/api/leads').json['total'],2)

    def test_cep_and_radius_validation_fail_closed(self):
        self.register()
        self.assertEqual(self.client.get('/api/postcodes/21235-112').status_code,200)
        for data in ({'postcode':'123'},{'postcode':'00000000'},{'radius_km':True},{'radius_km':0},{'radius_km':51},{'radius_km':float('nan')},{'require_phone':'yes'}):
            response = self.post_api({'term':'Cafe',**data})
            self.assertIn(response.status_code,(400,422))
        self.assertEqual(PlaceCollector.seen,[])

    def test_login_throttle_and_expired_session(self):
        self.register()
        token = self.client.get_cookie('leadfinder_auth').value
        with self.repo.connection() as db:
            db.execute('UPDATE auth_sessions SET expires_at=0')
        self.assertEqual(self.client.get('/api/overview').status_code,401)
        self.client.get('/login')
        for _ in range(8):
            self.assertEqual(self.client.post('/login',data={'csrf_token':self.csrf(),'username':'alice','password':'wrong'}).status_code,400)
        self.assertEqual(self.client.post('/login',data={'csrf_token':self.csrf(),'username':'alice','password':'correct-horse-123'}).status_code,429)


class MigrationTest(unittest.TestCase):
    def test_v1_backup_and_first_account_adopts_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'legacy.sqlite3'
            with sqlite3.connect(path) as db:
                db.executescript(Path('leadfinder/schema.sql').read_text(encoding='utf-8'))
                db.execute("INSERT INTO searches(id,term,max_results,created_at,status) VALUES('legacy','Cafe',10,'2026-10-27','completed')")
                db.execute("INSERT INTO leads(identity,name,maps_url,first_seen_at,last_seen_at) VALUES('place','Existing','https://example.org','2026-10-27','2026-10-27')")
                db.execute("INSERT INTO search_leads VALUES('legacy',1)")
            db.close()
            app = create_app({'TESTING':True,'DATABASE':str(path)},collector_factory=PlaceCollector)
            repo, store = app.extensions['repository'], app.extensions['accounts']
            self.assertTrue(Path(str(path)+'.phase1-backup.sqlite3').exists())
            user_id = store.create_user('First User','first','first@example.org','password-123')
            self.assertEqual(store.legacy_count(user_id),1)
            workspace = store.setup_workspace(user_id,'Imported workspace')
            self.assertEqual(repo.list_leads(workspace_id=workspace)['items'][0]['name'],'Existing')
            self.assertEqual(len(repo.get_lead(1,workspace)['searches']),1)
            repo.initialize()
            with repo.connection() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],8)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            other = store.create_user('Second User','second','second@example.org','password-123')
            self.assertEqual(repo.stats(store.setup_workspace(other,'Empty workspace'))['total'],0)


class GeographyTest(unittest.TestCase):
    def test_distance_and_provider_missing_coordinates(self):
        self.assertAlmostEqual(distance_km(0,0,0,0),0)
        self.assertAlmostEqual(distance_km(0,0,0,1),111.195,places=2)
        with patch('leadfinder.geography.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"location":{"coordinates":{}}}'
            with self.assertRaises(GeographyError):
                PostcodeResolver().resolve('21235112')

    def test_city_centroid_is_not_used_as_postcode_center(self):
        class Geocoder:
            def coordinates(self, postcode):
                return -22.86004, -43.33895
        with patch('leadfinder.geography.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"cep":"21235112","city":"Rio","street":"Av. Monsenhor Felix","location":{"coordinates":{"latitude":-22.90642,"longitude":-43.18223}}}'
            area = PostcodeResolver(geocoder=Geocoder()).resolve('21235112')
            self.assertEqual((area.latitude,area.longitude),(-22.86004,-43.33895))
