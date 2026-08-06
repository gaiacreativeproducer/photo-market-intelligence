"""Strict read-only CSV/JSON import inside an explicit directory."""
from __future__ import annotations
import csv,json
from pathlib import Path
from radar.models import ImportedRecord,SourceBatch
from .json_feed import mapped
class FileImportConnector:
    def __init__(self,source,import_directory,**kwargs):self.source=source;self.import_directory=Path(import_directory).resolve()
    def health_check(self):return None
    def validate_source_configuration(self):
        target=(self.import_directory/self.source.endpoint).resolve()
        if self.import_directory not in target.parents:raise ValueError("import path escapes configured directory")
        if target.suffix.casefold() not in {".csv",".json"}:raise ValueError("only CSV and JSON imports are supported")
        return target
    def fetch_records(self):
        target=self.validate_source_configuration();errors=[]
        if target.suffix.casefold()==".json":
            values=json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(values,list):raise ValueError("JSON import root must be an array")
        else:
            with target.open(newline="",encoding="utf-8") as handle:values=list(csv.DictReader(handle))
        records=[]
        for index,value in enumerate(values,1):
            if not isinstance(value,dict):errors.append(f"record {index} is malformed");continue
            records.append(ImportedRecord(value,f"record:{index}",True))
        return SourceBatch(records,errors)
    def normalize_record(self,record):return mapped(record.values,self.source.mapping)
