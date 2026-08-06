"""Explicit Italian and English intent patterns with stable precedence."""
from __future__ import annotations

import re
from .models import AssistantIntent

PATTERNS = {
    AssistantIntent.HELP: (r"\bhelp\b", r"\baiuto\b", r"cosa puoi fare"),
    AssistantIntent.SYSTEM_STATUS: (r"system status", r"stato (?:del )?(?:radar|connettori)", r"radar funziona"),
    AssistantIntent.COMPARE_PRODUCTS: (r"\bcompare\b", r"\bconfronta\b", r"differenze tra"),
    AssistantIntent.NEW_VS_USED: (r"new or used", r"nuov[oa] o usat[oa]", r"meglio nuov", r"conviene il nuovo"),
    AssistantIntent.EXPLAIN_RECOMMENDATION: (r"why (?:buy|recommend)", r"perch[eé].*(?:consiglia|raccomanda)", r"spiegami il punteggio"),
    AssistantIntent.EXPLAIN_WARNING: (r"explain.*warning", r"spiega.*avvis", r"perch[eé].*warning"),
    AssistantIntent.MARKET_SUMMARY: (r"market price", r"quanto vale", r"prezzo medio", r"andamento mercato"),
    AssistantIntent.LISTING_SUMMARY: (r"listing summary", r"riassumi.*annuncio", r"questo annuncio"),
    AssistantIntent.WISHLIST_STATUS: (r"wishlist", r"cosa sto monitorando"),
    AssistantIntent.INVENTORY_STATUS: (r"inventory", r"inventario", r"cosa possiedo"),
    AssistantIntent.PRODUCT_OVERVIEW: (r"tell me about", r"parlami", r"\bscheda\b"),
}
PRECEDENCE = tuple(PATTERNS)


def recognize_intent(message: str):
    text = message.casefold()
    matched = [intent for intent in PRECEDENCE if any(re.search(pattern, text) for pattern in PATTERNS[intent])]
    if not matched: return AssistantIntent.UNSUPPORTED, 25, False
    return matched[0], 95 if len(matched) == 1 else 85, False
