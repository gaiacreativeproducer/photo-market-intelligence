"""Manual listing entry and practical dashboard view tests."""
from __future__ import annotations

import ast,json,sys,tempfile,threading,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"))
from catalog import load_product_aliases,load_products
from dashboard.server import create_server
from radar.manual_entry import ManualEntryError,ManualListingService,validate_manual_payload
from radar.persistence import RadarStore
from radar.pipeline import RadarPipeline


def payload(**changes):
    value={"url":"https://www.subito.it/fotografia/a7.htm?utm_source=x#photo","source_name":"Subito.it",
        "title":"Sony A7 IV con 60000 scatti","description":"Fattura presente, scatola originale.",
        "price":1200,"currency":"EUR","source_country":"IT","segment":"USED","detected_at":None}
    value.update(changes);return value


class ValidationTests(unittest.TestCase):
    def test_url_price_and_schema_validation(self):
        value=validate_manual_payload(payload(price="1200,50"));self.assertEqual(value["price"],1200.5)
        self.assertNotIn("utm_source",value["url"]);self.assertNotIn("#",value["url"])
        for change in ({"url":"file:///tmp/a"},{"url":"https://user:pass@example.com/a"},{"price":0},{"price":"nan"}):
            with self.assertRaises(ManualEntryError):validate_manual_payload(payload(**change))
        invalid=payload();invalid["extra"]=True
        with self.assertRaises(ManualEntryError):validate_manual_payload(invalid)
        missing=payload();del missing["title"]
        with self.assertRaises(ManualEntryError):validate_manual_payload(missing)

    def test_no_network_and_duplicate_timestamps(self):
        products=load_products(ROOT/"data/products.csv");aliases=load_product_aliases(ROOT/"data/product_aliases.csv",products)
        with tempfile.TemporaryDirectory() as name:
            now=[datetime(2026,8,7,10,tzinfo=timezone.utc)]
            store=RadarStore(Path(name));pipeline=RadarPipeline(store,products,aliases,now=lambda:now[0])
            service=ManualListingService(pipeline,now=lambda:now[0]);first=service.submit(payload())
            initial=store.load_listings()[0];now[0]+=timedelta(hours=1);second=service.submit(payload(description="Fattura presente. seller@example.com +39 333 123 4567"))
            updated=store.load_listings()[0];self.assertEqual(first["status"],"created");self.assertEqual(second["status"],"updated")
            self.assertEqual(initial.first_seen_at,updated.first_seen_at);self.assertGreater(updated.last_seen_at,initial.last_seen_at)
            self.assertNotIn("seller@example.com",updated.description);self.assertNotIn("333 123",updated.description)
            self.assertEqual(updated.shutter_count,60000)

    def test_uncertain_record_is_persisted_for_review(self):
        products=load_products(ROOT/"data/products.csv");aliases=load_product_aliases(ROOT/"data/product_aliases.csv",products)
        with tempfile.TemporaryDirectory() as name:
            store=RadarStore(Path(name));result=ManualListingService(RadarPipeline(store,products,aliases)).submit(payload(title="Fotocamera usata",description="Buone condizioni"))
            self.assertEqual(result["status"],"needs_review");self.assertIsNone(result["product_id"]);self.assertFalse(store.load_listings()[0].product_id)

    def test_ambiguous_record_is_not_attached_to_a_candidate(self):
        products=load_products(ROOT/"data/products.csv");aliases=load_product_aliases(ROOT/"data/product_aliases.csv",products)
        with tempfile.TemporaryDirectory() as name:
            store=RadarStore(Path(name));result=ManualListingService(RadarPipeline(store,products,aliases)).submit(
                payload(title="Sony A7 III oppure Sony A7 IV",description="Uno dei due corpi macchina"))
            self.assertEqual(result["status"],"needs_review");self.assertIsNone(result["product_id"])
            self.assertFalse(store.load_listings()[0].product_id);self.assertGreaterEqual(len(result["plausible_candidates"]),2)


class ManualApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.runtime=Path(cls.temp.name);cls.server=create_server(0,False,ROOT,cls.runtime)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.port=cls.server.server_address[1];cls.base=f"http://127.0.0.1:{cls.port}"
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join(2);cls.temp.cleanup()
    def request(self,path,method="GET",value=None,headers=None,raw=None):
        data=raw if raw is not None else json.dumps(value).encode() if value is not None else None
        request=Request(self.base+path,data=data,method=method,headers=headers or {})
        try:
            with urlopen(request,timeout=3) as response:return response.status,response.headers,json.loads(response.read())
        except HTTPError as error:return error.code,error.headers,json.loads(error.read())
    def test_valid_subito_and_ebay_immediately_refresh(self):
        status,_,result=self.request("/api/listings/manual","POST",payload(),{"Content-Type":"application/json"})
        self.assertEqual(status,201);self.assertEqual(result["product_id"],"sony-alpha-a7-iv");self.assertEqual(result["extracted"]["shutter_count"],60000)
        live=self.request("/api/listings/live?product_id=sony-alpha-a7-iv&segment=USED&active=true")[2];self.assertEqual(live["count"],1)
        detail=self.request("/api/products/sony-alpha-a7-iv")[2];self.assertTrue(any(item.get("listing_id")==result["listing_id"] for item in detail["listings"]))
        ebay=payload(url="https://www.ebay.it/itm/1",source_name="eBay",title="Sony A7 IV",price="1300.25")
        self.assertEqual(self.request("/api/listings/manual","POST",ebay,{"Content-Type":"application/json"})[0],201)
    def test_review_listing_and_filters(self):
        review=payload(url="https://example.test/unknown",source_name="Other",title="Camera usata",description="Buone condizioni")
        result=self.request("/api/listings/manual","POST",review,{"Content-Type":"application/json"})[2];self.assertEqual(result["status"],"needs_review")
        values=self.request("/api/listings/live?source=Other&country=IT")[2]["items"];self.assertTrue(values[0]["needs_review"])
        self.assertEqual(self.request("/api/listings/live?bad=x")[0],400);self.assertEqual(self.request("/api/listings/live?active=maybe")[0],400)
    def test_memory_endpoints_are_allowlisted_and_empty(self):
        for endpoint in ("wishlist","inventory","decisions"):
            status,_,value=self.request(f"/api/{endpoint}");self.assertEqual(status,200);self.assertEqual(value["items"],[])
            serialized=json.dumps(value);self.assertNotIn("serial_reference",serialized);self.assertNotIn("notes",serialized)
    def test_security_validation_and_body_limit(self):
        self.assertEqual(self.request("/api/listings/manual","POST",payload(),{"Content-Type":"text/plain"})[0],415)
        self.assertEqual(self.request("/api/listings/manual","POST",payload(),{"Content-Type":"application/json","Origin":"null"})[0],403)
        self.assertEqual(self.request("/api/listings/manual","POST",{**payload(),"bad":1},{"Content-Type":"application/json"})[0],400)
        huge=Request(self.base+"/api/listings/manual",data=b"x"*262145,method="POST",headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(huge)
        self.assertEqual(caught.exception.code,413)
    def test_ui_accessibility_and_safe_rendering(self):
        html=(ROOT/"web/index.html").read_text();script=(ROOT/"web/manual-listing.js").read_text()+(ROOT/"web/app.js").read_text()
        self.assertIn("Aggiungi annuncio",html);self.assertIn('id="manual-panel" class="side-panel" hidden',html)
        self.assertGreaterEqual(html.count("data-view="),9);self.assertIn(".focus()",script);self.assertNotIn("innerHTML",script);self.assertIn("textContent",script)
        self.assertIn('"product_id","Product ID"',script);self.assertIn('select.name="active"',script);self.assertIn("Apply filters",script)
        self.assertIn("Non ci sono ancora dati di mercato reali",html)
    def test_python_39(self):
        ast.parse((ROOT/"src/radar/manual_entry.py").read_text(),feature_version=(3,9))


class DemoIsolationTests(unittest.TestCase):
    def test_demo_uses_temporary_runtime(self):
        real=ROOT/"data/user";before={p.name:p.read_bytes() for p in real.iterdir()} if real.is_dir() else {}
        server=create_server(0,True,ROOT);runtime=server.router.manual_service.pipeline.store.directory
        try:self.assertNotEqual(runtime.resolve(),real.resolve());server.router.manual_service.submit(payload())
        finally:server.server_close()
        after={p.name:p.read_bytes() for p in real.iterdir()} if real.is_dir() else {};self.assertEqual(before,after)


if __name__=="__main__":unittest.main()
