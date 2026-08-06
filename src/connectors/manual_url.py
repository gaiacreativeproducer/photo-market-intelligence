"""Manual supplied-record adapter; deliberately performs no HTTP request."""
from __future__ import annotations
import csv
from pathlib import Path
from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit
from radar.models import ImportedRecord,SourceBatch
FIELDS=("manual_id","url","source_name","title","description","price","currency","source_country","segment","detected_at","active")
TRACKING={"utm_source","utm_medium","utm_campaign","utm_term","utm_content","gclid","fbclid","ref","tracking"}
def normalize_url(value):
    parsed=urlsplit(value)
    if parsed.scheme not in {"http","https"} or not parsed.netloc:raise ValueError("manual URL must use HTTP(S)")
    if parsed.username or parsed.password:raise ValueError("embedded URL credentials are forbidden")
    query=urlencode([(k,v) for k,v in parse_qsl(parsed.query,keep_blank_values=True) if k.casefold() not in TRACKING])
    return urlunsplit((parsed.scheme,parsed.netloc,parsed.path,query,""))
class ManualUrlConnector:
    def __init__(self,source,user_directory=None,**kwargs):self.source=source;self.user_directory=Path(user_directory or ".")
    def health_check(self):return None
    def validate_source_configuration(self):return self.user_directory/self.source.endpoint
    def fetch_records(self):
        records=[];errors=[];seen=set()
        with self.validate_source_configuration().open(newline="",encoding="utf-8") as handle:
            reader=csv.DictReader(handle)
            if reader.fieldnames!=list(FIELDS):raise ValueError("manual listing header is invalid")
            for row_number,row in enumerate(reader,2):
                if (row["active"] or "").casefold() not in {"true","1"}:continue
                try:
                    value={"external_id":row["manual_id"],"url":normalize_url(row["url"]),"source_name":row["source_name"],"title":row["title"],"description":row["description"],"price":float(row["price"]) if row["price"] else None,"currency":row["currency"],"source_country":row["source_country"],"segment":row["segment"],"detected_at":row["detected_at"]}
                    key=(value["external_id"].casefold(),value["url"])
                    if key in seen:continue
                    seen.add(key);records.append(ImportedRecord(value,f"manual:{row['manual_id']}",True))
                except Exception:errors.append(f"row {row_number}: invalid manual record")
        return SourceBatch(records,errors)
    def normalize_record(self,record):return dict(record.values)
