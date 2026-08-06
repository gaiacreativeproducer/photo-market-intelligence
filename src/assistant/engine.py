"""Deterministic assistant orchestration and optional bounded history."""
from __future__ import annotations

import csv, os, re, tempfile, uuid
from datetime import datetime
from pathlib import Path

from .context import resolve_products
from .intents import recognize_intent
from .models import AssistantIntent
from .provider import AssistantProvider
from .responses import build_response


class DeterministicAssistantProvider(AssistantProvider):
    def __init__(self,data,user_directory=None,history_enabled=False):
        self.data=data; self.user_directory=Path(user_directory) if user_directory else None
        self.history_enabled=history_enabled
    def query(self,request):
        intent,confidence,_=recognize_intent(request.message)
        explicit=resolve_products(request.message,self.data)
        products=explicit or list(request.comparison_product_ids) or ([request.product_id] if request.product_id else [])
        products=[item for item in products if item in self.data.details][:4]
        if intent==AssistantIntent.COMPARE_PRODUCTS and len(explicit)>=2: products=explicit
        response=build_response(intent,confidence,self.data,products,request)
        if self.history_enabled: self._history(request,response)
        return response
    def capabilities(self):
        return {"provider":"deterministic","external_ai":False,"history_enabled":self.history_enabled,
                "intents":[item.value for item in AssistantIntent]}
    def _history(self,request,response):
        if not self.user_directory: return
        path=self.user_directory/"assistant_history.csv"; rows=[]
        if path.is_file():
            with path.open(newline="",encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
        rows.append({"interaction_id":uuid.uuid4().hex,"created_at":request.created_at.isoformat(),"intent":response.intent.value,
            "product_id":request.product_id or "","message_redacted":redact(request.message),"response_summary":response.answer[:200],"confidence":response.confidence})
        rows=rows[-100:]; self.user_directory.mkdir(parents=True,exist_ok=True)
        descriptor,name=tempfile.mkstemp(prefix=".assistant-history.",dir=str(self.user_directory))
        with os.fdopen(descriptor,"w",newline="",encoding="utf-8") as handle:
            writer=csv.DictWriter(handle,fieldnames=tuple(rows[0]));writer.writeheader();writer.writerows(rows);handle.flush();os.fsync(handle.fileno())
        os.replace(name,str(path))


def redact(value):
    patterns=(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",r"(?<!\w)(?:\+?\d[\s().-]*){8,15}(?!\w)",r"\b(?:\d[ -]*?){13,19}\b",r"\b(?:password|token|api[_ -]?key)\s*[:=]\s*\S+")
    for pattern in patterns:value=re.sub(pattern,"[removed]",value,flags=re.I)
    return value
