"""Sprint 12 notification, assistant, privacy, and API tests."""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import threading
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"))

from assistant import DeterministicAssistantProvider, ExternalAIProvider
from assistant.models import AssistantRequest
from dashboard.demo_data import DemoDashboardDataProvider
from dashboard.server import create_server
from notifications.engine import NotificationEngine
from notifications.models import DeliveryStatus, DigestMode, NotificationPreference
from notifications.persistence import NotificationStore
from notifications.rules import listing_candidates, manual_review_candidate
from radar.models import RunStatus

NOW=datetime(2026,8,6,12,tzinfo=timezone.utc)


def listing(**changes):
    values=dict(active=True,recognition_confidence=95,description_confidence=90,
        warnings=[],listing_id="listing",product_id="sony-alpha-a7-iv",source_id="source",
        title="Sony A7 IV",price=900.0,currency="EUR")
    values.update(changes);return SimpleNamespace(**values)


def watch(**changes):
    values=dict(active=True,product_id="sony-alpha-a7-iv",query="",source_ids=[],
                watch_id="watch",max_price=1000.0,currency="EUR")
    values.update(changes);return SimpleNamespace(**values)


class MemoryStore:
    def __init__(self,preference):self.preference=preference;self.values=[]
    def load_preferences(self):return self.preference
    def load(self):return list(self.values)
    def save(self,values):self.values=list(values)


class NotificationTests(unittest.TestCase):
    def test_new_price_and_high_confidence_rules(self):
        default=listing_candidates(listing(),[watch()],NotificationPreference(),NOW)
        self.assertEqual({x.notification_type.value for x in default},{"NEW_MATCH","PRICE_BELOW_TARGET"})
        enabled=replace(NotificationPreference(),notify_high_confidence_match=True)
        kinds={x.notification_type.value for x in listing_candidates(listing(),[watch()],enabled,NOW)}
        self.assertIn("HIGH_CONFIDENCE_MATCH",kinds)

    def test_global_maximum_currency_rules(self):
        matched=replace(NotificationPreference(),maximum_price=800,maximum_price_currency="EUR")
        self.assertEqual(listing_candidates(listing(),[watch()],matched,NOW),[])
        mismatch=replace(matched,maximum_price_currency="USD")
        values=listing_candidates(listing(),[watch()],mismatch,NOW)
        self.assertTrue(values);self.assertIn("global_maximum_note",values[0].evidence)

    def test_quiet_and_digest_persist_then_defer(self):
        for preference in (
            replace(NotificationPreference(),quiet_hours_start="11:00",quiet_hours_end="13:00"),
            replace(NotificationPreference(),digest_mode=DigestMode.DAILY),
        ):
            store=MemoryStore(preference);engine=NotificationEngine(store,[SimpleNamespace(send=lambda item:None)],now=lambda:NOW)
            run=SimpleNamespace(status=RunStatus.COMPLETED,run_id="r",source_failure_count=0)
            engine.evaluate_radar(run,[listing()],[watch()],[],[])
            self.assertTrue(store.values);self.assertTrue(all(x.delivery_status==DeliveryStatus.DEFERRED for x in store.values))

    def test_dedup_disabled_and_manual_review(self):
        store=MemoryStore(NotificationPreference());engine=NotificationEngine(store,now=lambda:NOW)
        run=SimpleNamespace(status=RunStatus.COMPLETED,run_id="r",source_failure_count=0)
        # no run candidate is emitted for completed runs
        engine.evaluate_radar(run,[listing()],[watch()],[],[]);count=len(store.values)
        engine.evaluate_radar(run,[listing()],[watch()],[],[]);self.assertEqual(len(store.values),count)
        self.assertEqual(manual_review_candidate("x","MONITOR",["reason"],product_id="p"),[])
        self.assertTrue(manual_review_candidate("x","MANUAL_REVIEW",["reason"],product_id="p",now=NOW))
        disabled=MemoryStore(replace(NotificationPreference(),enabled=False))
        self.assertEqual(NotificationEngine(disabled).evaluate_radar(run,[listing()],[watch()],[],[]),[])

    def test_atomic_persistence_read_dismiss_and_counts(self):
        with tempfile.TemporaryDirectory() as name:
            store=NotificationStore(Path(name));items=listing_candidates(listing(),[watch()],NotificationPreference(),NOW)
            store.save(items);self.assertEqual(len(store.load()),2)
            read=store.update_state(items[0].notification_id);self.assertTrue(read.read);self.assertFalse(read.dismissed)
            dismissed=store.update_state(items[1].notification_id,True);self.assertTrue(dismissed.read);self.assertTrue(dismissed.dismissed)


class AssistantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=DemoDashboardDataProvider(ROOT).load()
    def request(self,message,product=None,comparisons=None):return AssistantRequest(message,product,comparisons or [],None,"product",NOW)
    def test_intents_alias_resolution_and_precedence(self):
        provider=DeterministicAssistantProvider(self.data)
        overview=provider.query(self.request("Parlami della ILCE-7M4"))
        self.assertEqual(overview.intent.value,"PRODUCT_OVERVIEW");self.assertIn("sony-alpha-a7-iv",overview.related_product_ids)
        comparison=provider.query(self.request("Confronta A7 IV e S5 II"))
        self.assertEqual(comparison.intent.value,"COMPARE_PRODUCTS");self.assertGreaterEqual(len(comparison.related_product_ids),2)
        help_response=provider.query(self.request("Aiuto: confronta A7 IV e S5 II"))
        self.assertEqual(help_response.intent.value,"HELP")

    def test_supported_missing_and_noninvented_responses(self):
        provider=DeterministicAssistantProvider(self.data)
        self.assertEqual(provider.query(self.request("Meglio nuova o usata?","sony-alpha-a7-iv")).intent.value,"NEW_VS_USED")
        missing=provider.query(self.request("Quanto vale?","sony-fe-50mm-f1-8"))
        self.assertIn("unavailable",missing.answer.casefold())
        unsupported=provider.query(self.request("Compra questa fotocamera"));self.assertEqual(unsupported.intent.value,"UNSUPPORTED")

    def test_hard_limits_traceability_and_external_disabled(self):
        response=DeterministicAssistantProvider(self.data).query(self.request("Spiegami il punteggio","sony-alpha-a7-iv"))
        self.assertLessEqual(len(response.answer),600);self.assertLessEqual(len(response.facts),8)
        self.assertTrue(all(fact.source_module for fact in response.facts));self.assertTrue(0<=response.confidence<=100)
        self.assertFalse(ExternalAIProvider().capabilities()["enabled"])

    def test_history_disabled_default_and_enabled_redaction_retention(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);request=self.request("Parlami A7IV seller@example.com +39 333 123 4567")
            DeterministicAssistantProvider(self.data,root).query(request)
            self.assertFalse((root/"assistant_history.csv").exists())
            provider=DeterministicAssistantProvider(self.data,root,True)
            for _ in range(105):provider.query(request)
            text=(root/"assistant_history.csv").read_text();self.assertNotIn("seller@example.com",text);self.assertNotIn("333 123",text)
            self.assertEqual(len(text.splitlines()),101)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.server=create_server(0,True,ROOT,Path(cls.temp.name))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.port=cls.server.server_address[1];cls.base=f"http://127.0.0.1:{cls.port}"
        items=listing_candidates(listing(),[watch()],NotificationPreference(),NOW)
        cls.server.router.notification_store.save(items);cls.notification_id=items[0].notification_id
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join(2);cls.temp.cleanup()
    def request(self,path,method="GET",body=None,headers=None):
        data=json.dumps(body).encode() if body is not None else None
        request=Request(self.base+path,data=data,method=method,headers=headers or {})
        try:
            with urlopen(request,timeout=3) as response:return response.status,response.headers,json.loads(response.read())
        except HTTPError as error:return error.code,error.headers,json.loads(error.read())
    def test_capabilities_query_and_notification_state(self):
        self.assertEqual(self.request("/api/assistant/capabilities")[0],200)
        payload={"message":"Meglio nuova o usata?","product_id":"sony-alpha-a7-iv","comparison_product_ids":[],"listing_id":None,"page_context":"product"}
        status,headers,value=self.request("/api/assistant/query","POST",payload,{"Content-Type":"application/json"})
        self.assertEqual(status,200);self.assertEqual(value["intent"],"NEW_VS_USED");self.assertIsNone(headers.get("Access-Control-Allow-Origin"));self.assertIsNone(headers.get("Set-Cookie"))
        self.assertTrue(self.request(f"/api/notifications/{self.notification_id}/dismiss","POST",{}, {"Content-Type":"application/json"})[2]["read"])
        notifications=self.request("/api/notifications")[2];self.assertEqual(notifications["unread_count"],1);self.assertEqual(notifications["dismissed_count"],1)
    def test_post_security_and_limits(self):
        payload={"message":"help","product_id":None,"comparison_product_ids":[],"listing_id":None,"page_context":"home"}
        self.assertEqual(self.request("/api/assistant/query","POST",payload,{"Content-Type":"text/plain"})[0],415)
        self.assertEqual(self.request("/api/assistant/query","POST",payload,{"Content-Type":"application/json","Origin":"null"})[0],403)
        self.assertEqual(self.request("/api/assistant/query","POST",payload,{"Content-Type":"application/json","Origin":f"http://127.0.0.1:{self.port}"})[0],200)
        huge=Request(self.base+"/api/assistant/query",data=b"x"*65537,method="POST",headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as caught:urlopen(huge);self.assertEqual(caught.exception.code,413)
    def test_ui_is_secondary_safe_and_focus_restores(self):
        index=(ROOT/"web/index.html").read_text();scripts="\n".join((ROOT/"web"/name).read_text() for name in ("app.js","product.js","compare.js"))
        self.assertIn('id="assistant-panel" class="side-panel" hidden',index)
        self.assertIn(".focus()",scripts);self.assertNotIn("innerHTML",scripts);self.assertIn("textContent",scripts)
    def test_python_39(self):
        for directory in (ROOT/"src/notifications",ROOT/"src/assistant"):
            for path in directory.glob("*.py"):ast.parse(path.read_text(),feature_version=(3,9))


if __name__=="__main__":unittest.main()
