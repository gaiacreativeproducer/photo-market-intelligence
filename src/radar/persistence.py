"""Strict atomic CSV persistence for radar listings, runs, errors, and health."""
from __future__ import annotations
import csv,json,os,tempfile
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import List,Sequence
from .models import RadarError,RadarListing,RadarRun,RadarSourceHealth,RunStatus

LISTING_FIELDS=tuple(item.name for item in fields(RadarListing))
RUN_FIELDS=tuple(item.name for item in fields(RadarRun))
ERROR_FIELDS=tuple(item.name for item in fields(RadarError))
HEALTH_FIELDS=tuple(item.name for item in fields(RadarSourceHealth))

class RadarStore:
    def __init__(self,directory:Path):self.directory=directory;directory.mkdir(parents=True,exist_ok=True)
    @property
    def listings_path(self):return self.directory/"listings_live.csv"
    @property
    def runs_path(self):return self.directory/"radar_runs.csv"
    @property
    def errors_path(self):return self.directory/"radar_errors.csv"
    @property
    def health_path(self):return self.directory/"radar_source_health.csv"
    def load_listings(self):return _load(self.listings_path,RadarListing)
    def load_runs(self):return _load(self.runs_path,RadarRun)
    def load_errors(self):return _load(self.errors_path,RadarError)
    def load_health(self):return _load(self.health_path,RadarSourceHealth)
    def save_listings(self,values):_write(self.listings_path,LISTING_FIELDS,values)
    def save_runs(self,values):_write(self.runs_path,RUN_FIELDS,values)
    def save_errors(self,values):_write(self.errors_path,ERROR_FIELDS,values)
    def save_health(self,values):_write(self.health_path,HEALTH_FIELDS,values)

def _write(path,field_names,values):
    descriptor,name=tempfile.mkstemp(prefix=f".{path.name}.",dir=str(path.parent));temporary=Path(name)
    try:
        with os.fdopen(descriptor,"w",newline="",encoding="utf-8") as handle:
            writer=csv.DictWriter(handle,fieldnames=field_names);writer.writeheader()
            for value in values:writer.writerow({field:_encode(getattr(value,field)) for field in field_names})
            handle.flush();os.fsync(handle.fileno())
        os.replace(str(temporary),str(path))
    finally:
        if temporary.exists():temporary.unlink()

def _load(path,model):
    if not path.is_file():return []
    expected=tuple(item.name for item in fields(model));result=[]
    with path.open(newline="",encoding="utf-8") as handle:
        reader=csv.DictReader(handle)
        if tuple(reader.fieldnames or ())!=expected:raise ValueError(f"{path}: invalid radar schema")
        for row in reader:
            values={key:_decode(model,key,value) for key,value in row.items()};result.append(model(**values))
    return result

def _encode(value):
    if isinstance(value,datetime):return value.isoformat()
    if hasattr(value,"value"):return value.value
    if isinstance(value,(list,dict)):return json.dumps(value,ensure_ascii=False,separators=(",",":"))
    if value is None:return ""
    if isinstance(value,bool):return "true" if value else "false"
    return value

def _decode(model,key,value):
    if key in {"started_at","finished_at","occurred_at","detected_at","first_seen_at","last_seen_at","checked_at","last_success_at"}:return datetime.fromisoformat(value) if value else None
    if key=="status" and model is RadarRun:return RunStatus(value)
    if key in {"price"}:return float(value) if value else None
    if key in {"recognition_confidence","description_confidence","listing_count_raw","listing_count_normalized","listing_count_new","listing_count_ignored","incident_count","source_count","source_success_count","source_failure_count","response_time_ms","raw_record_count","normalized_record_count","relevant_persisted_count","consecutive_failures","shutter_count"}:return int(value) if value else (None if key=="shutter_count" else 0)
    if key in {"active","invoice_available","original_box_available","recoverable","resolved"}:return None if value=="" and key in {"invoice_available","original_box_available"} else value.casefold()=="true"
    if key in {"defects","accessories","seller_claims","missing_information","warnings"}:return json.loads(value or "[]")
    return value
