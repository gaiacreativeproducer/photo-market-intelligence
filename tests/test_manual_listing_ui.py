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
from dashboard.conclusions import build_overall_conclusion,market_sample_label
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
        live=self.request("/api/listings/live?product_id=sony-alpha-a7-iv&segment=USED&active=true")[2]
        self.assertTrue(any(item["listing_id"]==result["listing_id"] for item in live["items"]))
        detail=self.request("/api/products/sony-alpha-a7-iv")[2];self.assertTrue(any(item.get("listing_id")==result["listing_id"] for item in detail["listings"]))
        ebay=payload(url="https://www.ebay.it/itm/1",source_name="eBay",title="Sony A7 IV",price="1300.25")
        self.assertEqual(self.request("/api/listings/manual","POST",ebay,{"Content-Type":"application/json"})[0],201)

    def test_a7_iv_listing_to_decision_flow(self):
        new=payload(url="https://example.test/a7iv-new",source_name="Negozio",
            title="Sony A7 IV nuova",description="Remaining 24 months warranty. Fattura presente.",
            price=1595,segment="NEW")
        used=payload(url="https://example.test/a7iv-used",source_name="Privato",
            title="Sony A7 IV usata 60000 scatti",description="No warranty. Nessun difetto.",
            price=1200,segment="USED")
        new_result=self.request("/api/listings/manual","POST",new,{"Content-Type":"application/json"})[2]
        used_result=self.request("/api/listings/manual","POST",used,{"Content-Type":"application/json"})[2]
        self.assertEqual(new_result["product_id"],"sony-alpha-a7-iv")
        self.assertEqual(used_result["product_id"],"sony-alpha-a7-iv")
        live=self.request("/api/listings/live?product_id=sony-alpha-a7-iv&active=true")[2]["items"]
        pair=[item for item in live if item["listing_id"] in {new_result["listing_id"],used_result["listing_id"]}]
        self.assertEqual(len(pair),2)
        self.assertTrue(all(item["recognition_confidence"]==100 and not item["needs_review"] for item in pair))
        self.assertTrue(all(item["product_name"]=="Sony Alpha A7 IV" and item["title"] for item in pair))
        detail=self.request("/api/products/sony-alpha-a7-iv")[2]
        self.assertEqual(detail["product"]["new_median"],1595)
        self.assertEqual(detail["product"]["used_median"],1200)
        self.assertIn("EUR:NEW",detail["listing_market"]);self.assertIn("EUR:USED",detail["listing_market"])
        self.assertIn(new_result["listing_id"],detail["listing_decisions"])
        self.assertIn(used_result["listing_id"],detail["listing_decisions"])
        key=f'{new_result["listing_id"]}:{used_result["listing_id"]}'
        comparison=detail["ownership_comparisons"][key]
        self.assertEqual(comparison["nominal_saving"],395)
        self.assertAlmostEqual(comparison["saving_percentage"],24.8,places=1)
        self.assertTrue(comparison["recommendation"]);self.assertTrue(comparison["reasons"])
        self.assertTrue(used_result["listing_analysis"]["reasons"])
        self.assertTrue(used_result["comparable_offer_available"])
        self.assertEqual(used_result["active_offer_count"],2)
        self.assertTrue(used_result["comparison_available"])
        self.assertIn("#confronta",used_result["actions"]["compare_offers"])
        overall=detail["overall_conclusion"]
        self.assertEqual(detail["listing_decisions"][used_result["listing_id"]]["recommendation"],"BUY_NEW")
        self.assertEqual(comparison["recommendation"],"INSUFFICIENT_DATA")
        self.assertEqual(overall["result"],"INSUFFICIENT_DATA")
        self.assertEqual(overall["title"],"Confronto non ancora conclusivo")
        self.assertLessEqual(overall["confidence"],40)
        self.assertIn("Singola offerta osservata",detail["listing_market"]["EUR:USED"]["sample_label"])
        self.assertEqual(detail["listing_market"]["EUR:USED"]["price_label"],"Prezzo osservato")
        self.assertIn("Confidenza del confronto proprietà",overall["confidence_basis"])
        self.assertIn("Raccogliere dati storici di mercato",overall["suggested_checks"])
        self.assertEqual(pair[0]["recognition_confidence"],100)
        self.assertIn("description_confidence",pair[0])
        self.assertIn("market_confidence",detail["listing_market"]["EUR:USED"])
        self.assertIn("confidence",detail["listing_decisions"][used_result["listing_id"]])
        self.assertIn("confidence",comparison)
        workspace=detail["workspace"]
        self.assertEqual(workspace["offer_count"],2)
        self.assertEqual(len(workspace["active_offers"]),2)
        self.assertTrue(all(not item["state"]["needs_product_review"] for item in workspace["active_offers"]))
        catalog=self.request("/api/products?q=Sony+A7+IV")[2]["products"][0]
        self.assertEqual(catalog["active_offer_count"],2)
        self.assertEqual(catalog["lowest_new_offer"],1595)
        self.assertEqual(catalog["lowest_used_offer"],1200)

    def test_honest_comparison_boundaries_and_major_defect(self):
        single=payload(url="https://example.test/z6-single",title="Nikon Z6 III usata",price=1400)
        result=self.request("/api/listings/manual","POST",single,{"Content-Type":"application/json"})[2]
        self.assertFalse(result["comparable_offer_available"])
        self.assertEqual(result["listing_analysis"]["new_vs_used_recommendation"],"INSUFFICIENT_DATA")
        eur=payload(url="https://example.test/a7iii-used",title="Sony A7 III usata",price=900,currency="EUR")
        usd=payload(url="https://example.test/a7iii-new",title="Sony A7 III nuova",price=1200,currency="USD",segment="NEW")
        self.request("/api/listings/manual","POST",eur,{"Content-Type":"application/json"})
        self.request("/api/listings/manual","POST",usd,{"Content-Type":"application/json"})
        detail=self.request("/api/products/sony-alpha-a7-iii")[2]
        self.assertEqual(detail["ownership_comparisons"],{})
        clean_new=payload(url="https://example.test/a7v-new",title="Sony A7 V nuova",
            description="Remaining 24 months warranty.",price=2200,segment="NEW")
        self.request("/api/listings/manual","POST",clean_new,{"Content-Type":"application/json"})
        damaged=payload(url="https://example.test/a7v-damaged",title="Sony A7 V",
            description="Autofocus non funziona.",price=1600)
        damaged_result=self.request("/api/listings/manual","POST",damaged,{"Content-Type":"application/json"})[2]
        self.assertEqual(damaged_result["ownership_comparison"]["recommendation"],"MANUAL_REVIEW")
        self.assertEqual(damaged_result["overall_conclusion"]["result"],"MANUAL_REVIEW")

    def test_conclusion_precedence_and_sample_labels(self):
        valid=build_overall_conclusion({}, {"recommendation":"PREFER_USED","confidence":82}, {}, [])
        self.assertEqual(valid["result"],"PREFER_USED")
        manual=build_overall_conclusion({}, {"recommendation":"MANUAL_REVIEW","confidence":75}, {}, [])
        self.assertEqual(manual["result"],"MANUAL_REVIEW")
        self.assertEqual([market_sample_label(value) for value in (0,1,2,5,10)],
            ["Nessuna osservazione di mercato affidabile","Singola offerta osservata — non è una stima di mercato affidabile",
             "Campione di mercato molto limitato","Campione di mercato limitato","Campione di mercato"])
    def test_review_listing_and_filters(self):
        review=payload(url="https://example.test/unknown",source_name="Other",title="Camera usata",description="Buone condizioni")
        result=self.request("/api/listings/manual","POST",review,{"Content-Type":"application/json"})[2];self.assertEqual(result["status"],"needs_review")
        values=self.request("/api/listings/live?source=Other&country=IT")[2]["items"];self.assertTrue(values[0]["needs_review"])
        canonical=self.request("/api/listings?review=true")[2]
        self.assertEqual(canonical,self.request("/api/listings/live?review=true")[2])
        self.assertTrue(all(item["needs_review"] for item in canonical["items"]))

    def test_manual_product_assignment_change_and_removal(self):
        ambiguous=payload(
            url="https://example.test/manual-association-ambiguous",
            title="Sony A7 IV e Sony A7 III",
            description="Due corpi macchina venduti insieme.",
            price=1200,
        )
        created=self.request("/api/listings/manual","POST",ambiguous,{"Content-Type":"application/json"})[2]
        self.assertEqual(created["status"],"needs_review")
        listing_id=created["listing_id"]
        stored_before=next(item for item in self.server.router.manual_service.pipeline.store.load_listings() if item.listing_id==listing_id)
        path=f"/api/listings/{listing_id}/product"
        assigned=self.request(path,"POST",{"product_id":"sony-alpha-a7-iv"},{"Content-Type":"application/json"})
        self.assertEqual(assigned[0],200)
        value=assigned[2]
        self.assertFalse(value["needs_product_review"])
        self.assertEqual(value["product_id"],"sony-alpha-a7-iv")
        self.assertEqual(value["manual_association"]["source"],"USER")
        self.assertTrue(value["automatic_recognition"]["ambiguous"])
        self.assertEqual(value["automatic_recognition"]["confidence"],created["recognition_confidence"])
        review=self.request("/api/listings?review=true")[2]["items"]
        self.assertNotIn(listing_id,{item["listing_id"] for item in review})
        detail=self.request("/api/products/sony-alpha-a7-iv")[2]
        self.assertIn(listing_id,{item["listing_id"] for item in detail["workspace"]["active_offers"]})
        self.assertIn(listing_id,detail["workspace"]["listing_analyses"])
        changed=self.request(path,"POST",{"product_id":"nikon-z6-iii"},{"Content-Type":"application/json"})[2]
        self.assertEqual(changed["product_id"],"nikon-z6-iii")
        self.assertNotIn(listing_id,self.request("/api/products/sony-alpha-a7-iv")[2]["workspace"]["listing_analyses"])
        self.assertIn(listing_id,self.request("/api/products/nikon-z6-iii")[2]["workspace"]["listing_analyses"])
        removed=self.request(path,"POST",{"product_id":None},{"Content-Type":"application/json"})[2]
        self.assertTrue(removed["removed"])
        self.assertTrue(removed["needs_product_review"])
        self.assertIsNone(removed["manual_association"])
        stored_after=next(item for item in self.server.router.manual_service.pipeline.store.load_listings() if item.listing_id==listing_id)
        self.assertEqual(stored_after.listing_id,stored_before.listing_id)
        self.assertEqual(stored_after.first_seen_at,stored_before.first_seen_at)
        self.assertEqual(stored_after.product_id,stored_before.product_id)
        self.assertIn(listing_id,{item["listing_id"] for item in self.request("/api/listings?review=true")[2]["items"]})

    def test_manual_assignment_overrides_but_preserves_automatic_recognition(self):
        created=self.request("/api/listings/manual","POST",payload(
            url="https://example.test/manual-association-recognized",
            title="Sony A7 IV usata",
            description="Buone condizioni, 10000 scatti.",
        ),{"Content-Type":"application/json"})[2]
        listing_id=created["listing_id"]
        path=f"/api/listings/{listing_id}/product"
        value=self.request(path,"POST",{"product_id":"nikon-z6-iii"},{"Content-Type":"application/json"})[2]
        self.assertEqual(value["product_id"],"nikon-z6-iii")
        self.assertEqual(value["automatic_recognition"]["product_id"],"sony-alpha-a7-iv")
        self.assertEqual(value["automatic_recognition"]["confidence"],created["recognition_confidence"])
        fallback=self.request(path,"POST",{"product_id":None},{"Content-Type":"application/json"})[2]
        self.assertEqual(fallback["product_id"],"sony-alpha-a7-iv")
        self.assertFalse(fallback["needs_product_review"])

    def test_manual_assignment_rejects_invalid_requests(self):
        created=self.request("/api/listings/manual","POST",payload(
            url="https://example.test/manual-association-invalid",
            title="Camera sconosciuta",
        ),{"Content-Type":"application/json"})[2]
        path=f'/api/listings/{created["listing_id"]}/product'
        self.assertEqual(self.request(path,"POST",{"product_id":"not-a-product"},{"Content-Type":"application/json"})[0],400)
        self.assertEqual(self.request(path,"POST",{"product_id":42},{"Content-Type":"application/json"})[0],400)
        self.assertEqual(self.request(path,"POST",{"product_id":None,"extra":1},{"Content-Type":"application/json"})[0],400)
        self.assertEqual(self.request(path,"POST",{"product_id":None},{"Content-Type":"text/plain"})[0],415)
        self.assertEqual(self.request(path,"POST",{"product_id":None},{"Content-Type":"application/json","Origin":"null"})[0],403)

    def test_low_confidence_listing_can_be_manually_assigned(self):
        created=self.request("/api/listings/manual","POST",payload(
            url="https://example.test/manual-association-low-confidence",
            title="Fotocamera usata",
            description="Condizioni buone.",
        ),{"Content-Type":"application/json"})[2]
        self.assertLess(created["recognition_confidence"],70)
        value=self.request(f'/api/listings/{created["listing_id"]}/product',"POST",
            {"product_id":"sony-alpha-a7-iv"},{"Content-Type":"application/json"})[2]
        self.assertEqual(value["product_id"],"sony-alpha-a7-iv")
        self.assertFalse(value["needs_product_review"])
        self.assertEqual(value["automatic_recognition"]["confidence"],created["recognition_confidence"])
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
        html=(ROOT/"web/index.html").read_text();script=(ROOT/"web/manual-listing.js").read_text()+(ROOT/"web/app.js").read_text()+(ROOT/"web/product-association.js").read_text()
        self.assertIn("Aggiungi annuncio",html);self.assertIn('id="manual-panel" class="side-panel" hidden',html)
        self.assertGreaterEqual(html.count("data-view="),9);self.assertIn(".focus()",script);self.assertNotIn("innerHTML",script);self.assertIn("textContent",script)
        self.assertIn('"product_id","Product ID"',script);self.assertIn('select.name="active"',script);self.assertIn("Apply filters",script)
        self.assertIn("Non ci sono ancora dati di mercato reali",html)
        self.assertIn("Associa prodotto",html);self.assertIn("Cambia prodotto associato",script)
        self.assertIn("Riconoscimento automatico",script);self.assertIn("Associazione manuale",script)
        self.assertIn("/api/search?q=",script);self.assertIn("product_id: productId",script)
    def test_python_39(self):
        ast.parse((ROOT/"src/radar/manual_entry.py").read_text(),feature_version=(3,9))
        ast.parse((ROOT/"src/dashboard/listing_analysis.py").read_text(),feature_version=(3,9))


class DemoIsolationTests(unittest.TestCase):
    def test_demo_uses_temporary_runtime(self):
        real=ROOT/"data/user";before={p.name:p.read_bytes() for p in real.iterdir() if p.is_file()} if real.is_dir() else {}
        server=create_server(0,True,ROOT);runtime=server.router.manual_service.pipeline.store.directory
        try:self.assertNotEqual(runtime.resolve(),real.resolve());server.router.manual_service.submit(payload())
        finally:server.server_close()
        after={p.name:p.read_bytes() for p in real.iterdir() if p.is_file()} if real.is_dir() else {};self.assertEqual(before,after)


if __name__=="__main__":unittest.main()
