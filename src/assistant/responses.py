"""Concise deterministic response templates over allowlisted dashboard data."""
from __future__ import annotations

from .models import AssistantFact, AssistantIntent, AssistantResponse


def build_response(intent, confidence, data, product_ids, request):
    facts=[]; warnings=[]; actions=[]; sections=[]
    detail = data.details.get(product_ids[0]) if product_ids else None
    answer = "I can summarize products, markets, listings, memory, and system status."
    if intent == AssistantIntent.HELP:
        actions=["Ask about a product", "Ask for market status", "Compare two products"]
    elif intent == AssistantIntent.SYSTEM_STATUS:
        answer=f"Latest radar status: {data.context.get('latest_radar_status') or 'unavailable'}."
        facts=[_fact("Live listings", data.context.get("live_listing_count", 0), "radar")]
        sections=["system status"]
    elif intent == AssistantIntent.WISHLIST_STATUS:
        count=data.context.get("active_wishlist_count",0); answer=f"You have {count} active wishlist item(s)."
        facts=[_fact("Active wishlist", count, "memory")]; sections=["wishlist"]
    elif intent == AssistantIntent.INVENTORY_STATUS:
        owned=data.context.get("owned_product_ids",[]); answer=f"You have {len(owned)} active catalog item(s) recorded."
        facts=[_fact("Owned products", len(owned), "memory")]; sections=["inventory"]
    elif intent == AssistantIntent.COMPARE_PRODUCTS:
        if len(product_ids)<2:
            return _clarify("Name two to four products to compare.", product_ids)
        answer=f"Comparing {len(product_ids)} catalog products."
        for product_id in product_ids[:4]:
            product=data.details[product_id]["product"]
            facts.append(_fact(product.display_name, f"{product.category}; {product.native_mount}", "catalog"))
        actions=["Open the comparison table"]; sections=["comparison"]
    elif not detail:
        return _clarify("Select or name a catalog product.", product_ids)
    elif intent == AssistantIntent.PRODUCT_OVERVIEW:
        product=detail["product"]; answer=f"{product.display_name} is a {product.product_type}."
        facts=[_fact("Category",product.category,"catalog"),_fact("Mount",product.native_mount,"catalog"),_fact("Release year",product.release_year or "Unavailable","catalog")]
        sections=["overview"]
    elif intent == AssistantIntent.MARKET_SUMMARY:
        market=detail["market"].get("used")
        if not market: answer="Market statistics are unavailable for this product."; warnings=["A valid market snapshot is needed."]
        else:
            answer="Existing used-market statistics are available."
            facts=[_fact("Used median",market.get("median"),"market",market.get("market_confidence",0)),_fact("Sample size",market.get("sample_size"),"market",market.get("market_confidence",0))]
        sections=["market"]
    elif intent == AssistantIntent.NEW_VS_USED:
        result=detail.get("new_vs_used")
        if not result: answer="No existing new-versus-used recommendation is available."; warnings=["A DecisionReport is needed."]
        else: answer=f"Existing recommendation: {result.get('recommendation')}."; facts=[_fact("Confidence",result.get("confidence"),"decision",result.get("confidence",0))]
        sections=["new vs used"]
    elif intent == AssistantIntent.EXPLAIN_RECOMMENDATION:
        result=detail.get("new_vs_used")
        if not result: return _clarify("No structured recommendation is available to explain.", product_ids)
        answer=f"The existing recommendation is {result.get('recommendation')}."
        facts=[_fact(item.get("name","Factor"),item.get("explanation",""),"decision") for item in result.get("factors",[])[:8]]; sections=["decision"]
    elif intent == AssistantIntent.EXPLAIN_WARNING:
        values=detail.get("warnings",[])
        if not values: return _clarify("No structured warning is available to explain.", product_ids)
        answer="The product view contains structured warnings."; warnings=values[:4]; sections=["warnings"]
    elif intent == AssistantIntent.LISTING_SUMMARY:
        listings=detail.get("listings",[]); selected=next((x for x in listings if request.listing_id and x.get("listing_id")==request.listing_id),None) or (listings[0] if listings else None)
        if not selected: answer="No persisted live listing is available."; warnings=["A listing record is needed."]
        else: answer=f"{selected.get('title','Listing')} from {selected.get('source','unknown source')}."; facts=[_fact("Price",f"{selected.get('currency','')} {selected.get('price')}","radar"),_fact("Condition",selected.get("condition") or "Unavailable","radar")]
        sections=["listings"]
    else:
        answer="This request is not supported by the deterministic assistant."
        warnings=["Try product, market, comparison, wishlist, inventory, or system questions."]
    return bounded(AssistantResponse(answer,intent,confidence,facts,warnings,actions,product_ids,sections))


def bounded(response):
    answer=response.answer[:600]
    return AssistantResponse(answer,response.intent,max(0,min(100,response.confidence)),response.facts[:8],response.warnings[:4],response.suggested_actions[:3],response.related_product_ids[:4],response.source_sections[:6])


def _fact(label,value,module,confidence=100): return AssistantFact(str(label),str(value),module,max(0,min(100,int(confidence or 0))))
def _clarify(answer,products): return bounded(AssistantResponse(answer,AssistantIntent.UNSUPPORTED,40,[],["Clarification required."],[],products,[]))
