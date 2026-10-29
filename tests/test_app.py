import tempfile
import threading
import time
import unittest
from pathlib import Path

from leadfinder import create_app
from leadfinder.collectors.parsing import parse_place, place_identity
from leadfinder.models import Lead


class AppTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE": str(Path(self.temp.name) / "test.sqlite3"), "API_TOKEN": "test"}, collector_factory=lambda: FakeCollector())
        self.client = self.app.test_client()
        self.repo = self.app.extensions["repository"]
        self.client.get('/register')
        with self.client.session_transaction() as session:
            token = session['csrf']
        response = self.client.post('/register', data={'csrf_token':token,'name':'Test User','username':'testuser','email':'test@example.org','password':'test-password-123','password_confirmation':'test-password-123'})
        self.assertEqual(response.status_code, 303)
        self.client.get('/setup')
        with self.client.session_transaction() as session:
            token = session['csrf']
        self.assertEqual(self.client.post('/setup', data={'csrf_token':token,'workspace_name':'Test workspace'}).status_code,303)
        self.workspace = self.app.extensions['accounts'].workspace(1)['id']
        with self.client.session_transaction() as session:
            session['csrf'] = 'test'
        self.headers = {"X-LeadFinder-Token": "test"}

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, data):
        return self.client.post(path, json=data, headers=self.headers)

    def await_search(self, search_id):
        for _ in range(200):
            search = self.repo.get_search(search_id)
            if search["status"] not in {"running", "queued"}:
                return search
            time.sleep(.01)
        self.fail("Worker did not finish")

    def test_empty_app_and_security(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/leads").json["total"], 0)
        self.assertEqual(self.client.post("/api/searches", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/overview", headers={"Host": "evil.example"}).status_code, 403)
        response = self.client.get("/")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_validation(self):
        for body in ({}, {"term": "a"}, {"term": "Cafe", "max_results": True}, {"term": "Cafe", "max_results": 101}, {"term": "Cafe", "location": []}, []):
            self.assertEqual(self.post("/api/searches", body).status_code, 400)
        self.assertEqual(self.client.get("/api/leads?page=0").status_code, 400)
        self.assertEqual(self.client.get("/api/leads?page=bad").status_code, 400)
        self.assertEqual(self.post("/api/searches/missing/cancel", {}).status_code, 404)

    def test_background_collection_and_deduplication(self):
        for _ in range(2):
            response = self.post("/api/searches", {"term": "Cafeterias", "location": "Rio", "max_results": 10})
            self.assertEqual(response.status_code, 202)
            result = self.await_search(response.json["id"])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["saved"], 1)
        leads = self.client.get("/api/leads").json
        self.assertEqual(leads["total"], 1)
        lead = self.client.get(f'/api/leads/{leads["items"][0]["id"]}').json
        self.assertEqual(lead["phone"], "(21) 99999-1111")
        self.assertEqual(len(lead["searches"]), 2)
        self.assertEqual(self.repo.stats(self.workspace), {"total": 1, "with_phone": 1, "with_website": 1})

    def test_upsert_keeps_previous_fields_and_first_seen(self):
        self.repo.create_search("s", "Cafe", "", 10)
        self.repo.save_lead("s", Lead("place", "Cafe", "https://www.google.com/maps/place/Cafe", phone="123", details={"description": "Cafe de bairro"}))
        first = self.repo.list_leads(workspace_id=self.workspace)["items"][0]
        self.repo.save_lead("s", Lead("place", "Cafe novo", first["maps_url"], website="https://example.org", details={"price": "R$ 20–40"}))
        after = self.repo.list_leads(workspace_id=self.workspace)["items"][0]
        self.assertEqual(after["phone"], "123")
        self.assertEqual(after["name"], "Cafe novo")
        self.assertEqual(after["first_seen_at"], first["first_seen_at"])
        self.assertEqual(after["details"], {"description": "Cafe de bairro", "price": "R$ 20–40"})

    def test_pagination_search_filter_and_literal_like(self):
        self.repo.create_search("s", "Cafe", "", 30)
        for i in range(27):
            self.repo.save_lead("s", Lead(str(i), f"Cafe {i}", f"https://example.org/{i}"))
        self.assertEqual(len(self.client.get("/api/leads").json["items"]), 25)
        self.assertEqual(len(self.client.get("/api/leads?page=2").json["items"]), 2)
        self.assertEqual(self.client.get("/api/leads?q=%25").json["total"], 0)
        self.assertEqual(self.client.get("/api/leads?q=%27%20OR%201%3D1").json["total"], 0)
        self.assertEqual(self.client.get("/api/leads?search_id=missing").json["total"], 0)
        self.assertEqual(self.client.get("/api/leads?search_id=s").json["total"], 27)

    def test_cancellation_and_busy_worker(self):
        entered, release = threading.Event(), threading.Event()

        class BlockingCollector:
            def collect(self, term, location, limit, on_lead, on_error, progress, check_cancel):
                on_lead(Lead("1", "Salvo antes da interrupção", "https://example.org", phone='21999990000'))
                entered.set()
                release.wait(5)
                check_cancel()

        self.app.extensions["search_service"].collector_factory = BlockingCollector
        search = self.post("/api/searches", {"term": "Cafe"}).json
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.post("/api/searches", {"term": "Outro"}).status_code, 409)
            self.assertEqual(self.post(f'/api/searches/{search["id"]}/cancel', {}).status_code, 200)
        finally:
            release.set()
        self.assertEqual(self.await_search(search["id"])["status"], "cancelled")
        self.assertEqual(self.repo.stats(self.workspace)["total"], 1)

    def test_partial_and_actionable_failure(self):
        class PartialCollector(FakeCollector):
            def collect(self, term, location, limit, on_lead, on_error, progress, check_cancel):
                super().collect(term, location, limit, on_lead, on_error, progress, check_cancel)
                on_error("Página indisponível")

        self.app.extensions["search_service"].collector_factory = PartialCollector
        result = self.await_search(self.post("/api/searches", {"term": "Cafe"}).json["id"])
        self.assertEqual((result["status"], result["saved"], result["failed"]), ("partial", 1, 1))

        class BrokenCollector:
            def collect(self, *args):
                from leadfinder.collectors.google_maps import CollectorError
                raise CollectorError("Google solicitou CAPTCHA")

        self.app.extensions["search_service"].collector_factory = BrokenCollector
        with self.assertLogs("leadfinder.services", level="ERROR"):
            result = self.await_search(self.post("/api/searches", {"term": "Cafe"}).json["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("CAPTCHA", result["message"])

    def test_recovery_and_persistence(self):
        self.repo.create_search("s", "Cafe", "", 10)
        self.repo.save_lead("s", Lead("1", "Cafe", "https://example.org"))
        self.repo.recover_interrupted()
        self.assertEqual(self.repo.get_search("s")["status"], "interrupted")
        other = create_app(self.app.config, collector_factory=FakeCollector)
        self.assertEqual(other.extensions["repository"].stats(self.workspace)["total"], 1)


class FakeCollector:
    def collect(self, term, location, limit, on_lead, on_error, progress, check_cancel):
        progress(found=1)
        on_lead(Lead("place-1", "Café de teste", "https://www.google.com/maps/place/Test", phone="(21) 99999-1111", website="https://example.org"))


class ParsingTest(unittest.TestCase):
    def test_public_place_fields(self):
        url = "https://www.google.com/maps/place/Cafe/data=!4m2!1s0x123:0xabc!3d-22.91!4d-43.21?hl=pt-BR"
        lead = parse_place({"name": " Café ", "phone": "Telefone: (21) 98765-4321", "address": "Endereço: Rua Um, 10", "rating": "4,8 estrelas", "review_count": "2.146 avaliações", "website": "https://example.org", "hours": "Segunda: 08:00–18:00"}, url)
        self.assertEqual(lead.identity, "0x123:0xabc")
        self.assertEqual(lead.phone, "(21) 98765-4321")
        self.assertEqual(lead.rating, 4.8)
        self.assertEqual(lead.review_count, 2146)
        self.assertEqual((lead.latitude, lead.longitude), (-22.91, -43.21))
        self.assertEqual(lead.address, "Rua Um, 10")
        self.assertEqual(place_identity(url.replace("Cafe", "Outro")), lead.identity)

    def test_missing_fields_and_unsafe_links(self):
        lead = parse_place({"name": "Teste", "website": "javascript:alert(1)"}, "https://example.org/place")
        self.assertIsNone(lead.phone)
        self.assertIsNone(lead.rating)
        self.assertIsNone(lead.website)
        with self.assertRaises(ValueError):
            parse_place({}, "https://example.org")


if __name__ == "__main__":
    unittest.main()
