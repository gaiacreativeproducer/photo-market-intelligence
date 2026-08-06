"""Coherent presentation conclusions over existing engine reports."""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Sequence

from radar.models import RadarListing


VALID_OWNERSHIP_RESULTS = {
    "PREFER_NEW", "PREFER_USED", "EQUIVALENT", "NEGOTIATE_USED", "WAIT",
}


def market_sample_label(valid_sample_size: int) -> str:
    if valid_sample_size <= 0:
        return "Nessuna osservazione di mercato affidabile"
    if valid_sample_size == 1:
        return "Singola offerta osservata — non è una stima di mercato affidabile"
    if valid_sample_size <= 4:
        return "Campione di mercato molto limitato"
    if valid_sample_size <= 9:
        return "Campione di mercato limitato"
    return "Campione di mercato"


def build_overall_conclusion(
    decisions: Mapping[str, Dict[str, object]],
    comparison: Optional[Dict[str, object]],
    market: Mapping[str, Dict[str, object]],
    listings: Sequence[RadarListing],
) -> Dict[str, object]:
    """Apply presentation precedence without changing any engine result."""
    required_samples = [
        int(value.get("valid_sample_size", 0))
        for value in market.values()
        if value.get("segment") in {"NEW", "USED"}
    ]
    sparse_required_market = len(required_samples) < 2 or any(
        sample < 2 for sample in required_samples
    )
    available_confidences = [
        int(value["confidence"]) for value in decisions.values()
        if value.get("confidence") is not None
    ] + [
        int(value["market_confidence"]) for value in market.values()
        if value.get("market_confidence") is not None
    ] + [item.recognition_confidence for item in listings] + [
        item.description_confidence for item in listings
    ]

    ownership_result = comparison.get("recommendation") if comparison else None
    if ownership_result == "MANUAL_REVIEW":
        result = "MANUAL_REVIEW"
        title = "Confronto da verificare manualmente"
    elif ownership_result == "INSUFFICIENT_DATA":
        result = "INSUFFICIENT_DATA"
        title = "Confronto non ancora conclusivo"
    elif ownership_result in VALID_OWNERSHIP_RESULTS:
        result = str(ownership_result)
        title = _valid_title(result)
    else:
        result = "NO_COMPARISON"
        title = "Conclusione nuovo/usato non disponibile"

    confidence = (
        int(comparison.get("confidence", 0))
        if comparison else min(available_confidences, default=0)
    )
    if sparse_required_market:
        confidence = min(confidence, 50)
    if result == "INSUFFICIENT_DATA":
        confidence = min(confidence, 40)

    new_items = [item for item in listings if item.segment == "NEW"]
    used_items = [item for item in listings if item.segment == "USED"]
    facts = [
        f"Offerte osservate: {len(new_items)} NEW e {len(used_items)} USED",
    ]
    if comparison:
        saving = comparison.get("nominal_saving")
        percentage = comparison.get("saving_percentage")
        currency = comparison.get("currency") or ""
        if saving is not None:
            facts.append(f"Risparmio nominale usato: {float(saving):.2f} {currency}".strip())
        if percentage is not None:
            facts.append(f"Risparmio usato: {float(percentage):.1f}%")
        ownership_label = "dati insufficienti" if ownership_result == "INSUFFICIENT_DATA" else str(ownership_result)
        facts.append(f"Confronto proprietà: {ownership_label}")
    used_shutters = [item.shutter_count for item in used_items if item.shutter_count is not None]
    if used_shutters:
        facts.append(f"Scatti usato: {min(used_shutters):,}".replace(",", "."))

    explanation = _explanation(decisions, comparison, sparse_required_market, listings)
    checks = _suggested_checks(listings, comparison)
    return {
        "result": result,
        "title": title,
        "confidence": confidence,
        "confidence_basis": (
            "Confidenza del confronto proprietà, con limiti per evidenza di mercato"
            if comparison else
            "Minimo delle confidenze disponibili, con limiti per evidenza di mercato"
        ),
        "key_facts": facts,
        "explanation": explanation,
        "suggested_checks": checks,
        "ownership_result": ownership_result,
        "has_complete_comparison": comparison is not None,
    }


def _valid_title(result: str) -> str:
    return {
        "PREFER_NEW": "Il nuovo offre attualmente il miglior equilibrio",
        "PREFER_USED": "L'usato offre attualmente il miglior valore",
        "EQUIVALENT": "Nuovo e usato risultano sostanzialmente equivalenti",
        "NEGOTIATE_USED": "Conviene negoziare il prezzo dell'usato",
        "WAIT": "Conviene attendere prima di decidere",
    }[result]


def _explanation(
    decisions: Mapping[str, Dict[str, object]],
    comparison: Optional[Dict[str, object]], sparse_market: bool,
    listings: Sequence[RadarListing],
) -> Sequence[str]:
    used_ids = {item.listing_id for item in listings if item.segment == "USED"}
    values = [value for key, value in decisions.items() if key in used_ids] or list(decisions.values())
    listing_results = list(dict.fromkeys(str(value.get("recommendation")) for value in values))
    lines = []
    if listing_results:
        lines.append(
            "Le regole sui singoli annunci indicano: " + ", ".join(listing_results)
            + ". Questa non è la conclusione complessiva nuovo/usato."
        )
    if comparison and comparison.get("recommendation") == "INSUFFICIENT_DATA":
        lines.append("Il motore di proprietà non dispone di evidenza sufficiente per confermare una preferenza.")
    if sparse_market:
        lines.append("Le offerte osservate non costituiscono ancora un campione di mercato affidabile.")
    if comparison and any(
        projection and projection.get("estimated_resale_value") is None
        for projection in (comparison.get("new_projection"), comparison.get("used_projection"))
    ):
        lines.append("Manca una base storica sufficiente per stimare in modo affidabile la svalutazione e la rivendita.")
    return lines


def _suggested_checks(
    listings: Sequence[RadarListing], comparison: Optional[Dict[str, object]]
) -> Sequence[str]:
    missing = {
        value.casefold()
        for item in listings for value in item.missing_information
    }
    checks = []
    if "warranty status" in missing or any(
        item.segment == "USED" and not item.warranty_until for item in listings
    ):
        checks.append("Verificare la garanzia dell'usato")
    if "condition details" in missing:
        checks.append("Verificare condizioni e numero di scatti")
    checks.append("Aggiungere altre offerte comparabili")
    if not comparison or comparison.get("break_even_used_price") is None:
        checks.append("Raccogliere dati storici di mercato")
    return list(dict.fromkeys(checks))
