"""Validated dashboard manual entry using the existing radar processing path."""
from __future__ import annotations

import math
import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict

from connectors.manual_url import normalize_url
from notifications import NotificationEngine, NotificationStore

from .models import RadarRun, RadarSource, RunStatus, SourceType
from .pipeline import RadarPipeline

FIELDS={"url","source_name","title","description","price","currency","source_country","segment","detected_at"}


class ManualEntryError(ValueError):
    def __init__(self,field,message):super().__init__(message);self.field=field;self.message=message


class ManualListingService:
    def __init__(self,pipeline:RadarPipeline,watches=(),now=None):
        self.pipeline=pipeline;self.watches=list(watches);self.now=now or (lambda:datetime.now(timezone.utc))

    def submit(self,payload:Dict[str,object]):
        value=validate_manual_payload(payload);now=self.now();run_id=uuid.uuid4().hex
        source_id="manual-ui-"+re.sub(r"[^a-z0-9]+","-",value["source_name"].casefold()).strip("-")[:50]
        source=RadarSource(source_id,value["source_name"],SourceType.MANUAL_URL,"",True,
            value["source_country"],value["currency"],value["segment"],15,0,0,{})
        categories={item.id:item.category for item in self.pipeline.products}
        candidate,_relevant,recognition=self.pipeline._to_listing(
            run_id,source,value,"manual-ui",True,self.watches,now,categories)
        confident=bool(recognition.product_id and recognition.confidence>=70 and not recognition.ambiguous)
        if not confident:
            candidate=replace(candidate,product_id="")
        existing=self.pipeline.store.load_listings()
        listings,created=self.pipeline._upsert(existing,candidate)
        persisted=next(item for item in listings if item.duplicate_key==candidate.duplicate_key)
        run=RadarRun(run_id,now,now,RunStatus.COMPLETED,1,1,0,1,1,int(created),0,0,"manual entry completed")
        self.pipeline.store.save_listings(listings)
        self.pipeline.store.save_runs(self.pipeline.store.load_runs()+[run])
        try:
            NotificationEngine(NotificationStore(self.pipeline.store.directory)).evaluate_radar(
                run,[persisted] if created else [],self.watches,[],[],False)
        except Exception:
            pass
        product_id=recognition.product_id if confident else None
        products={item.id:item for item in self.pipeline.products}
        product=products.get(product_id)
        plausible=[]
        for item in recognition.candidates[:4]:
            match=products.get(item.product_id)
            if match: plausible.append({"product_id":match.id,"name":" ".join(x for x in (match.brand,match.model,match.version) if x),"confidence":item.score})
        return {"status":"created" if created and confident else "updated" if not created and confident else "needs_review",
            "listing_id":persisted.listing_id,"product_id":product_id,
            "recognized_product":" ".join(x for x in (product.brand,product.model,product.version) if x) if product else None,
            "recognition_confidence":recognition.confidence,"description_confidence":persisted.description_confidence,
            "extracted":{"shutter_count":persisted.shutter_count,"warranty_until":persisted.warranty_until,
                "invoice_available":persisted.invoice_available,"original_box_available":persisted.original_box_available,
                "accessories":persisted.accessories,"defects":persisted.defects,"seller_claims":persisted.seller_claims,
                "missing_information":persisted.missing_information},"warnings":persisted.warnings,
            "plausible_candidates":plausible,"product_url":f"/product.html?id={product_id}" if product_id else None}


def validate_manual_payload(payload):
    if set(payload)!=FIELDS:
        unknown=set(payload)-FIELDS;missing=FIELDS-set(payload)
        raise ManualEntryError("request",f"unknown field: {sorted(unknown)[0]}" if unknown else f"missing field: {sorted(missing)[0]}")
    result={}
    for field,limit in (("source_name",80),("title",300),("description",20000)):
        value=payload[field]
        if not isinstance(value,str) or not value.strip() or len(value.strip())>limit:raise ManualEntryError(field,f"{field} is required and must not exceed {limit} characters")
        result[field]=value.strip()
    try:result["url"]=normalize_url(str(payload["url"]))
    except ValueError as exc:raise ManualEntryError("url",str(exc))
    raw=payload["price"]
    try:value=float(raw.replace(",",".")) if isinstance(raw,str) else float(raw)
    except (TypeError,ValueError):raise ManualEntryError("price","price must be a positive number")
    if not math.isfinite(value) or value<=0:raise ManualEntryError("price","price must be a positive finite number")
    result["price"]=value
    currency=payload["currency"]
    country=payload["source_country"]
    if not isinstance(currency,str) or not re.fullmatch(r"[A-Z]{3}",currency):raise ManualEntryError("currency","currency must be three uppercase letters")
    if not isinstance(country,str) or not re.fullmatch(r"[A-Z]{2}",country):raise ManualEntryError("source_country","country must be two uppercase letters")
    if payload["segment"] not in {"NEW","USED"}:raise ManualEntryError("segment","segment must be NEW or USED")
    detected=payload["detected_at"]
    if detected is not None:
        if not isinstance(detected,str):raise ManualEntryError("detected_at","detected_at must be ISO-8601 or null")
        try:datetime.fromisoformat(detected.replace("Z","+00:00"))
        except ValueError:raise ManualEntryError("detected_at","detected_at must be ISO-8601 or null")
    result.update(currency=currency,source_country=country,segment=payload["segment"],detected_at=detected,external_id="")
    return result
