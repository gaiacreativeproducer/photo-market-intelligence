"""Public RSS/Atom structured-feed adapter."""
from __future__ import annotations
import xml.etree.ElementTree as ET
from radar.importers import extract_structured_price
from radar.models import ImportedRecord,SourceBatch
from .json_feed import JsonFeedConnector

class RssFeedConnector(JsonFeedConnector):
    allowed_content_types={"application/rss+xml","application/atom+xml","application/xml","text/xml"}
    def fetch_records(self):
        self.validate_source_configuration();from urllib.request import Request
        with self.opener(Request(self.source.endpoint,method="GET",headers={"User-Agent":"Photo-Market-Intelligence-Radar/1"}),timeout=self.source.request_timeout_seconds) as response:
            if response.headers.get_content_type() not in self.allowed_content_types: raise ValueError("unexpected content type")
            body=response.read(self.max_response_bytes+1)
            if len(body)>self.max_response_bytes: raise ValueError("response exceeds size limit")
        root=ET.fromstring(body);nodes=root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry");records=[];errors=[]
        for index,node in enumerate(nodes,1):
            def get(*names):
                for name in names:
                    child=node.find(name)
                    if child is not None:return child.get("href") or (child.text or "")
                return ""
            value={"external_id":get("guid","{http://www.w3.org/2005/Atom}id"),"url":get("link","{http://www.w3.org/2005/Atom}link"),"title":get("title","{http://www.w3.org/2005/Atom}title"),"description":get("description","summary","{http://www.w3.org/2005/Atom}summary"),"detected_at":get("pubDate","updated","{http://www.w3.org/2005/Atom}updated")}
            config=self.source.mapping.get("price_extraction")
            if config:
                try:value["price"]=extract_structured_price(value["description"],config)
                except ValueError as exc:errors.append(f"record {index}: {exc}")
            records.append(ImportedRecord(value,f"record:{index}"))
        return SourceBatch(records,errors)
    def normalize_record(self,record):return dict(record.values)
