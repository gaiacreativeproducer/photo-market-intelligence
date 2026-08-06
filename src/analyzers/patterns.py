"""Structured Italian and English patterns used by description analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Pattern, Tuple


FLAGS = re.IGNORECASE | re.UNICODE
NUMBER = r"\d{1,3}(?:[.,]\d{3})+|\d{4,7}|\d{1,3}\s*(?:k|mila)"


@dataclass(frozen=True)
class PatternDefinition:
    name: str
    fact_type: str
    pattern: Pattern[str]
    confidence: int
    category: Optional[str] = None
    severity: Optional[str] = None
    affected_component: Optional[str] = None


def definition(name: str, fact_type: str, expression: str, confidence: int = 95,
               category: Optional[str] = None, severity: Optional[str] = None,
               component: Optional[str] = None) -> PatternDefinition:
    return PatternDefinition(
        name, fact_type, re.compile(expression, FLAGS), confidence,
        category, severity, component,
    )


SHUTTER_PATTERNS = (
    definition("count_before_scatti", "shutter_count", rf"(?P<value>{NUMBER})\s*(?:scatti|actuations)"),
    definition("shutter_count", "shutter_count", rf"shutter\s*count\s*[:=]?\s*(?P<value>{NUMBER})"),
    definition("otturatore_count", "shutter_count", rf"otturatore\s+(?:a|con)\s*(?P<value>{NUMBER})"),
)

WARRANTY_DATE_PATTERNS = (
    definition("warranty_numeric_date", "warranty_until", r"(?:garanzia\s+fino\s+al|warranty\s+until)\s+(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>20\d{2})"),
    definition("warranty_month_year", "warranty_until", r"(?:garanzia\s+fino\s+(?:ad?|al)?|warranty\s+until)\s*(?P<month_name>[a-zà]+)\s+(?P<year>20\d{2})"),
)
WARRANTY_RELATIVE_PATTERNS = (
    definition("remaining_warranty", "warranty_until", r"(?:ancora|remaining)\s+(?P<months>\d+|un[oa]?|due|tre|quattro|cinque|sei|one|two|three|four|five|six)\s+(?:mesi|months?)\s+(?:di\s+)?(?:garanzia|warranty)"),
)
IMPRECISE_WARRANTY_PATTERNS = (
    definition("recent_purchase_warranty", "warranty_claim", r"acquistat[ao]\s+(?:\w+\s+){0,2}mesi\s+fa\s+con\s+garanzia(?:\s+italiana)?", 70),
)

INVOICE_POSITIVE = (
    definition("invoice_present", "invoice_available", r"\b(?:fattura\s+presente|con\s+fattura|ricevuta\s+disponibile|scontrino\s+disponibile|invoice\s+included|proof\s+of\s+purchase)\b"),
)
INVOICE_NEGATIVE = (
    definition("invoice_absent", "invoice_available", r"\b(?:senza\s+fattura|fattura\s+smarrita|no\s+receipt)\b"),
)
BOX_POSITIVE = (
    definition("box_present", "original_box_available", r"\b(?:scatola\s+originale|confezione\s+originale|imballo\s+originale|original\s+box|complete\s+packaging)\b"),
)
BOX_NEGATIVE = (
    definition("box_absent", "original_box_available", r"\b(?:senza\s+scatola|scatola\s+non\s+inclusa|no\s+original\s+box)\b"),
)

SELLER_CLAIM_PATTERNS = (
    definition("like_new", "seller_claim", r"\bpari\s+al\s+nuovo\b", 65),
    definition("meticulous", "seller_claim", r"\btenut[ao]\s+maniacalmente\b", 60),
    definition("little_used", "seller_claim", r"\busat[ao]\s+pochissimo\b", 60),
    definition("no_photo_effect", "seller_claim", r"\bnon\s+influisce\s+(?:sulle|nelle)\s+foto\b", 55),
    definition("fully_working", "seller_claim", r"\bperfettamente\s+funzionante\b", 65),
    definition("no_defects_claim", "seller_claim", r"\bnessun\s+difetto\b", 60),
    definition("professional_quality", "seller_claim", r"\bqualit[àa]\s+professionale\b", 55),
    definition("rare", "seller_claim", r"\brar[ao]\b", 50),
    definition("bargain_claim", "seller_claim", r"\bprezzo\s+affare\b", 50),
)

NEGATED_DEFECT_PATTERNS = (
    definition("no_scratches", "verified_negative", r"\b(?:nessun\s+graffio|senza\s+graffi|no\s+scratches)\b", category="scratches"),
    definition("no_fungus", "verified_negative", r"\b(?:senza\s+funghi|nessun\s+fungo|no\s+fungus)\b", category="fungus"),
    definition("no_haze", "verified_negative", r"\b(?:(?:senza|né)\s+haze|nessuna\s+velatura|no\s+haze)\b", category="haze"),
    definition("no_water", "verified_negative", r"\b(?:non\s+ha\s+preso\s+acqua|nessun\s+danno\s+da\s+acqua|no\s+water\s+damage)\b", category="water_damage"),
)

DEFECT_PATTERNS = (
    definition("front_element_crack", "defect", r"\b(?:lente|elemento)\s+frontale\s+(?:crepat[ao]|incrinat[ao])\b|\bcracked\s+front\s+(?:element|glass)\b", category="cracks", severity="critical", component="front element"),
    definition("front_element_scratch", "defect", r"\b(?:graffio|graffi)\s+(?:(?:molto\s+)?evident[ei]\s+)?sulla\s+lente\s+frontale\b|\b(?:visible|deep)\s+scratch(?:es)?\s+on\s+(?:the\s+)?front\s+element\b", category="scratches", severity="major", component="front element"),
    definition("rear_element_scratch", "defect", r"\b(?:graffio|graffi)\s+sulla\s+lente\s+posteriore\b|\bscratch(?:es)?\s+on\s+(?:the\s+)?rear\s+element\b", category="scratches", severity="major", component="rear element"),
    definition("generic_scratches", "defect", r"\b(?:presenta\s+graffi|has\s+scratches)\b", category="scratches", severity="unknown", component="other"),
    definition("damaged_front_element", "defect", r"\b(?:elemento|lente)\s+frontale\s+danneggiat[ao]\b|\bdamaged\s+front\s+element\b", category="optical_damage", severity="major", component="front element"),
    definition("damaged_rear_element", "defect", r"\b(?:elemento|lente)\s+posteriore\s+danneggiat[ao]\b|\bdamaged\s+rear\s+element\b", category="optical_damage", severity="major", component="rear element"),
    definition("vague_optical_damage", "defect", r"\b(?:danno\s+ottico|problema\s+ottico|optical\s+damage)\b", category="optical_damage", severity="unknown", component="optics"),
    definition("fungus", "defect", r"\b(?:presenza\s+di\s+funghi|fungo\s+interno|fungus)\b", category="fungus", severity="unknown", component="optics"),
    definition("haze", "defect", r"\b(?:presenza\s+di\s+haze|velatura\s+interna|internal\s+haze|\bhaze\b)\b", category="haze", severity="unknown", component="optics"),
    definition("internal_dust", "defect", r"\b(?:leggera|lieve|light)\s+(?:polvere\s+interna|internal\s+dust)\b", category="dust", severity="minor", component="optics"),
    definition("filter_thread", "defect", r"\b(?:filettatura\s+(?:del\s+)?filtro\s+(?:ammaccata|danneggiata)|damaged\s+filter\s+thread)\b", category="mechanical_damage", severity="moderate", component="filter thread"),
    definition("autofocus_failure", "defect", r"\b(?:autofocus|af)\s+(?:non\s+funziona|guasto|does\s+not\s+work|not\s+working)\b", category="electronic_damage", severity="major", component="autofocus system"),
    definition("stabilization_failure", "defect", r"\b(?:stabilizzazione|stabilization|ibis)\s+(?:non\s+funziona|guasta|does\s+not\s+work|not\s+working)\b", category="mechanical_damage", severity="major", component="stabilization system"),
    definition("sensor_damage", "defect", r"\b(?:sensore\s+danneggiato|sensor\s+damage|damaged\s+sensor)\b", category="electronic_damage", severity="major", component="sensor"),
    definition("broken_display", "defect", r"\b(?:display|schermo)\s+(?:rotto|danneggiato|broken|damaged)\b", category="electronic_damage", severity="major", component="display"),
    definition("body_scratch", "defect", r"\b(?:piccolo|lieve|minor|small)\s+graffio\s+sulla\s+(?:scocca|body)\b", category="cosmetic_damage", severity="minor", component="body"),
    definition("generic_cosmetic_damage", "defect", r"\b(?:danno\s+estetico|cosmetic\s+damage)\b", category="cosmetic_damage", severity="unknown", component="body"),
    definition("generic_mechanical_damage", "defect", r"\b(?:danno\s+meccanico|mechanical\s+damage)\b", category="mechanical_damage", severity="unknown", component="other"),
    definition("generic_electronic_damage", "defect", r"\b(?:danno\s+elettronico|electronic\s+damage)\b", category="electronic_damage", severity="unknown", component="other"),
    definition("water_damage", "defect", r"\b(?:danno\s+da\s+acqua|water\s+damage)\b", category="water_damage", severity="unknown", component="body"),
    definition("missing_part", "defect", r"\b(?:manca|missing)\s+(?P<component>copriobiettivo|battery\s+door|sportello\s+batteria|lens\s+cap)\b", category="missing_parts", severity="moderate", component="other"),
)

ACCESSORY_PATTERNS = (
    definition("battery_prefix_quantity", "accessory", r"\b(?P<quantity>\d+|un[oa]?|due|tre|quattro|cinque|sei|one|two|three|four|five|six)\s+(?P<details>(?:(?:original|original[ei])\s+)?(?:sony|nikon|canon|panasonic|patona)(?:\s+[a-z0-9-]+){0,2})\s+batter(?:ia|ie|y|ies)\b", 92),
    definition("battery_with_quantity", "accessory", r"\b(?P<quantity>\d+|un[oa]?|due|tre|quattro|cinque|sei|one|two|three|four|five|six)\s+batter(?:ia|ie|y|ies)\s+(?P<details>(?:original[ei]?\s+)?(?:sony|nikon|canon|panasonic|patona)?(?:\s+[a-z0-9-]+){0,2})", 90),
    definition("battery_model_quantity", "accessory", r"\b(?P<quantity>\d+|un[oa]?|due|tre|quattro|cinque|sei|one|two|three|four|five|six)\s+(?P<model>[a-z]{1,4}-[a-z0-9-]+)\s+original[ei]?\b", 95),
    definition("smallrig_cage", "accessory", r"\bSmallRig(?:\s+[A-Z0-9-]+)?\s+cage\b", 95),
    definition("nisi_filter", "accessory", r"\bfiltro\s+NiSi\s+[A-Za-z0-9-]+(?:\s+[A-Za-z0-9-]+){0,3}\b|\bNiSi\s+[A-Za-z0-9-]+(?:\s+[A-Za-z0-9-]+){0,3}\s+filter\b", 95),
    definition("dji_gimbal", "accessory", r"\bDJI\s+RS\s*\d(?:\s+(?:Mini|Pro))?\b", 95),
    definition("patona_charger", "accessory", r"\bcaricatore\s+(?:doppio\s+)?Patona(?:\s+[A-Za-z0-9-]+)?\b|\bPatona(?:\s+[A-Za-z0-9-]+)?\s+charger\b", 90),
    definition("identified_accessory", "accessory", r"\b(?P<brand>Sony|Nikon|Canon|Panasonic|SmallRig|NiSi|DJI|Patona|Rode|Atomos|Godox|Lowepro|Manfrotto)\s+(?P<model>[A-Z0-9][A-Z0-9-]{1,})\s+(?P<kind>charger|caricatore|grip|cage|filter|filtro|bag|borsa|strap|tracolla|microphone|microfono|monitor|flash|gimbal|memory\s+card|scheda\s+di\s+memoria|lens\s+hood|paraluce|adapter|adattatore)\b", 92),
)
