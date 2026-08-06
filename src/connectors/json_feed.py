"""Safe structured JSON feed adapter; never parses HTML."""
from __future__ import annotations
import ipaddress,json,socket
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
from radar.models import ImportedRecord,SourceBatch

class JsonFeedConnector:
    allowed_content_types={"application/json","application/feed+json"}
    def __init__(self,source,allow_private_network=False,max_response_bytes=5*1024*1024,opener=urlopen,**kwargs): self.source=source;self.allow_private_network=allow_private_network;self.max_response_bytes=max_response_bytes;self.opener=opener
    def health_check(self): return None
    def validate_source_configuration(self):
        parsed=urlsplit(self.source.endpoint)
        if parsed.scheme not in {"http","https"} or not parsed.hostname: raise ValueError("HTTP(S) endpoint required")
        if parsed.username or parsed.password: raise ValueError("embedded URL credentials are forbidden")
        if not self.allow_private_network:
            for info in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=="https" else 80),type=socket.SOCK_STREAM):
                address=ipaddress.ip_address(info[4][0])
                if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified: raise ValueError("private or unsafe network destination rejected")
    def fetch_records(self):
        self.validate_source_configuration();request=Request(self.source.endpoint,method="GET",headers={"User-Agent":"Photo-Market-Intelligence-Radar/1"})
        with self.opener(request,timeout=self.source.request_timeout_seconds) as response:
            kind=response.headers.get_content_type()
            if kind not in self.allowed_content_types: raise ValueError(f"unexpected content type: {kind}")
            body=response.read(self.max_response_bytes+1)
            if len(body)>self.max_response_bytes: raise ValueError("response exceeds size limit")
        root=json.loads(body.decode("utf-8"));records=root
        for part in str(self.source.mapping.get("list_path","")).split(".") if self.source.mapping.get("list_path") else []:
            if not isinstance(records,dict) or part not in records: raise ValueError("configured list_path not found")
            records=records[part]
        if not isinstance(records,list): raise ValueError("JSON record root must be an array")
        return SourceBatch([ImportedRecord(item,f"record:{i}") for i,item in enumerate(records,1) if isinstance(item,dict)],[f"record {i} is not an object" for i,item in enumerate(records,1) if not isinstance(item,dict)])
    def normalize_record(self,record): return mapped(record.values,self.source.mapping)

def mapped(value,mapping):
    result={}
    for target in ("external_id","url","title","description","price","currency","source_country","segment","condition","detected_at"):
        source=mapping.get(target)
        if not source: continue
        current=value
        for part in str(source).split("."): current=current.get(part) if isinstance(current,dict) else None
        result[target]=current
    return result
