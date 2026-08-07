"use strict";

const params = new URLSearchParams(location.search);
const productId = params.get("id");
const selectedOffers = new Set((params.get("offers") || "").split(",").filter(Boolean));
const el = id => document.getElementById(id);
const node = (tag, value, className) => { const item = document.createElement(tag); item.textContent = value; if (className) item.className = className; return item; };
const money = (value, currency) => value == null ? "Non disponibile" : new Intl.NumberFormat("it-IT", {style: "currency", currency: currency || "EUR"}).format(value);

function add(root, label, value) {
    if (value == null) return;
    const row = node("p", "");
    row.append(node("strong", `${label}: `), document.createTextNode(String(value)));
    root.append(row);
}

function safeLink(item) {
    try {
        const url = new URL(item.url);
        if(!["http:","https:"].includes(url.protocol))return null;
        const link = node("a", "Apri originale");
        link.href = url.href;
        link.target = "_blank";
        link.rel="noopener noreferrer";
        return link;
    } catch (error) { return null; }
}

function renderWorkspaceHeader(workspace) {
    const product = workspace.product;
    el("title").textContent = product.display_name;
    add(el("identity"), "Categoria", product.product_type);
    add(el("identity"), "Offerte attive", workspace.offer_count);
    if (product.owned) el("identity").append(node("span", "Nel corredo", "badge"));
    if (product.wishlist) el("identity").append(node("span", "Wishlist", "badge"));
    const overall = workspace.overall_conclusion;
    el("conclusion").textContent = overall?.title || "Nessuna conclusione disponibile";
    if (overall) {
        add(el("overall-details"), "Confidenza complessiva", `${overall.confidence}%`);
        overall.key_facts.forEach(value => el("overall-details").append(node("p", value)));
        overall.explanation.forEach(value => el("overall-details").append(node("p", value)));
    }
    workspace.warnings.forEach(value => el("overall-details").append(node("p", value, "warning")));
}

function updateOfferUrl() {
    const next = new URLSearchParams(location.search);
    if (selectedOffers.size) next.set("offers", [...selectedOffers].join(",")); else next.delete("offers");
    history.replaceState(null, "", `${location.pathname}?${next}${location.hash}`);
}

function offerCard(item, workspace) {
    const card = node("article", "", "listing-card");
    card.append(node("h3", item.title), node("p", `${item.segment} · ${money(item.price, item.currency)} · ${item.source}`));
    [["Paese", item.country], ["Condizione", item.condition], ["Scatti", item.shutter_count], ["Garanzia", item.warranty_status],
     ["Difetti", item.defects.length ? item.defects.map(value => value.description).join(", ") : "Nessuno rilevato"],
     ["Accessori", item.accessories.length ? item.accessories.join(", ") : "Non specificati"],
     ["Confidenza riconoscimento", `${item.recognition_confidence}%`], ["Confidenza descrizione", `${item.description_confidence}%`],
     ["Informazioni mancanti", item.missing_information_count]].forEach(([label, value]) => add(card, label, value));
    const actions = node("div", "", "actions");
    const analyze = node("a", "Analizza");
    analyze.href = `#analisi-${item.listing_id}`;
    const compareLabel = node("label", "", "offer-select");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selectedOffers.has(item.listing_id);
    checkbox.addEventListener("change", () => {
        if (checkbox.checked) selectedOffers.add(item.listing_id); else selectedOffers.delete(item.listing_id);
        updateOfferUrl();
        renderOfferComparison(workspace);
    });
    compareLabel.append(checkbox, document.createTextNode(" Confronta"));
    actions.append(analyze, compareLabel);
    const original = safeLink(item);
    if (original) actions.append(original);
    card.append(actions);
    return card;
}

function renderOffers(workspace) {
    workspace.active_offers.forEach(item => el("listings").append(offerCard(item, workspace)));
    if (!workspace.active_offers.length) el("listings").append(node("p", "Nessuna offerta attiva raccolta."));
}

function difference(selected) {
    if (new Set(selected.map(item => item.currency)).size !== 1) return null;
    const prices = selected.filter(item => item.price != null);
    if (prices.length < 2) return null;
    const high = Math.max(...prices.map(item => item.price));
    const low = Math.min(...prices.map(item => item.price));
    return {absolute: high - low, percentage: high ? (high - low) / high * 100 : null};
}

function comparisonKey(selected) {
    const fresh = selected.find(item => item.segment === "NEW");
    const used = selected.find(item => item.segment === "USED");
    return fresh && used ? `${fresh.listing_id}:${used.listing_id}` : null;
}

function renderOfferComparison(workspace) {
    const root = el("comparison-table");
    root.replaceChildren();
    const selected = workspace.active_offers.filter(item => selectedOffers.has(item.listing_id));
    el("selection-status").textContent = selected.length < 2 ? "Seleziona almeno due offerte dello stesso prodotto." : `${selected.length} offerte selezionate`;
    if (selected.length < 2) return;
    const table = document.createElement("table");
    const fields = [
        ["Fonte", item => item.source], ["Tipo", item => item.segment],
        ["Prezzo", item => money(item.price, item.currency)], ["Scatti", item => item.shutter_count],
        ["Garanzia", item => item.warranty_status], ["Condizione", item => item.condition],
        ["Difetti", item => item.defects.length ? item.defects.map(value => value.description).join(", ") : "Nessuno rilevato"],
        ["Accessori", item => item.accessories.length ? item.accessories.join(", ") : "Non specificati"],
        ["Valutazione annuncio", item => workspace.listing_analyses[item.listing_id]?.recommendation],
        ["Rischio", item => workspace.listing_analyses[item.listing_id]?.warnings?.join(", ") || "Nessun rischio strutturato"],
        ["Informazioni mancanti", item => item.missing_information?.join(", ") || "Nessuna"],
    ];
    fields.forEach(([label, valueFor]) => {
        const row = document.createElement("tr");
        row.append(node("th", label));
        selected.forEach(item => row.append(node("td", valueFor(item) ?? "Non disponibile")));
        table.append(row);
    });
    root.append(table);
    const delta = difference(selected);
    if (delta) {
        add(root, "Differenza assoluta", money(delta.absolute, selected[0].currency));
        add(root, "Differenza percentuale", `${delta.percentage.toFixed(1)}%`);
    } else if (new Set(selected.map(item => item.currency)).size !== 1) root.append(node("p", "Differenza non calcolata: le offerte usano valute diverse e non viene applicata alcuna conversione."));
    const key = comparisonKey(selected);
    const ownership = key ? workspace.available_comparisons[key] : null;
    if (ownership && selected.every(item => item.currency === selected[0].currency)) renderOwnershipReport(root, ownership, workspace.comparison_conclusions[key]);
    else root.append(node("p", key ? "Confronto proprietà non disponibile per valute incompatibili o dati insufficienti." : "Confronto fattuale: per il Nuovo vs usato seleziona almeno una offerta NEW e una USED."));
}

function renderMarket(workspace) {
    const values = Object.values(workspace.market_snapshots);
    values.forEach(value => {
        const block = node("article", "");
        block.append(node("h3", `${value.segment} · ${value.currency}`), node("p", value.sample_label));
        add(block, value.price_label, money(value.median, value.currency));
        add(block, "Osservazioni valide", value.valid_sample_size);
        add(block, "Confidenza mercato", `${value.market_confidence}%`);
        el("market-section").append(block);
    });
    if (!values.length) el("market-section").append(node("p", "Nessun dato di mercato disponibile"));
}

function offerById(workspace, id) { return workspace.active_offers.find(item => item.listing_id === id); }

function renderAnalyses(workspace) {
    Object.entries(workspace.listing_analyses).forEach(([listingId, report]) => {
        const offer = offerById(workspace, listingId);
        const block = node("article", "", "analysis-card");
        block.id = `analisi-${listingId}`;
        block.append(node("h3", "Analisi annuncio"), node("p", offer ? `${offer.source} · ${offer.segment} · ${money(offer.price, offer.currency)}` : listingId));
        add(block, "Raccomandazione", report.recommendation);
        add(block, "Punteggio", `${report.buy_score}/100`);
        add(block, "Confidenza", `${report.confidence}%`);
        report.reasons.forEach(value => block.append(node("p", value)));
        el("explanation").append(block);
    });
}

function renderOwnershipReport(root, value, conclusion) {
    if (conclusion) {
        root.append(node("h3", conclusion.title));
        add(root, "Confidenza complessiva", `${conclusion.confidence}%`);
    }
    add(root, "Risultato Ownership", value.recommendation);
    add(root, "Risparmio nominale", money(value.nominal_saving, value.currency));
    add(root, "Risparmio", value.saving_percentage == null ? null : `${value.saving_percentage.toFixed(1)}%`);
    add(root, "Prezzo di pareggio usato", money(value.break_even_used_price, value.currency));
    add(root, "Costo lordo NEW", money(value.new_projection?.gross_cost_without_resale, value.currency));
    add(root, "Costo lordo USED", money(value.used_projection?.gross_cost_without_resale, value.currency));
    add(root, "Protezione NEW", value.new_projection?.protection_score);
    add(root, "Protezione USED", value.used_projection?.protection_score);
    value.warnings.forEach(warning => root.append(node("p", warning, "warning")));
}

function renderOwnership(workspace) {
    const key = workspace.selected_comparison;
    const value = key ? workspace.available_comparisons[key] : null;
    if (!value) { el("ownership").append(node("p", "Confronto nuovo/usato non disponibile: servono offerte NEW e USED compatibili.")); return; }
    renderOwnershipReport(el("ownership"), value, workspace.comparison_conclusions[key] || workspace.overall_conclusion);
}

function renderMissing(workspace) {
    workspace.missing_information.forEach(value => el("risks").append(node("p", value)));
    workspace.overall_conclusion?.suggested_checks.forEach(value => el("risks").append(node("p", value)));
    if (!el("risks").children.length) el("risks").append(node("p", "Nessuna informazione critica mancante."));
}

function renderMemory(workspace) {
    add(el("memory"), "Nel corredo", workspace.memory_context.owned ? "Sì" : "No");
    add(el("memory"), "Wishlist", workspace.memory_context.wishlist ? "Sì" : "No");
}

async function load() {
    if (!productId) { el("message").textContent = "ID prodotto mancante."; return; }
    const response = await fetch(`/api/products/${encodeURIComponent(productId)}`);
    const data = await response.json();
    if (!response.ok) { el("message").textContent = data.error.message; return; }
    const workspace = data.workspace;
    renderWorkspaceHeader(workspace);
    renderOffers(workspace);
    renderOfferComparison(workspace);
    renderMarket(workspace);
    renderAnalyses(workspace);
    renderOwnership(workspace);
    renderMissing(workspace);
    renderMemory(workspace);
}

load();
let assistantOpener = null;
el("assistant-open").addEventListener("click", () => { assistantOpener = el("assistant-open"); el("assistant-panel").hidden = false; el("assistant-close").focus(); });
el("assistant-close").addEventListener("click", () => { el("assistant-panel").hidden = true; assistantOpener.focus(); });
el("assistant-form").addEventListener("submit", async event => {
    event.preventDefault();
    const response = await fetch("/api/assistant/query", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({message: el("assistant-message").value, product_id: productId, comparison_product_ids: [], listing_id: null, page_context: "product"})});
    const data = await response.json();
    el("assistant-response").textContent = data.answer || data.error?.message;
});
