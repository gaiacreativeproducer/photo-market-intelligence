"use strict";

const manualOpen = document.getElementById("add-listing-open");
const manualPanel = document.getElementById("manual-panel");
const manualClose = document.getElementById("manual-close");
const manualForm = document.getElementById("manual-form");
const manualResult = document.getElementById("manual-result");
let manualBusy = false;

function closeManual() {
    if (manualBusy) return;
    manualPanel.hidden = true;
    manualOpen.focus();
}

function resultRow(label, value) {
    const row = document.createElement("p");
    const strong = document.createElement("strong");
    strong.textContent = `${label}: `;
    row.append(strong, document.createTextNode(value == null ? "Non disponibile" : String(value)));
    manualResult.append(row);
}

function actionLink(label, href, primary = false) {
    if (!href) return;
    const link = document.createElement("a");
    link.textContent = label;
    link.href = href;
    if (primary) link.className = "primary-action";
    manualResult.append(link);
}

function renderSuccess(data) {
    resultRow("Stato", data.status === "needs_review" ? "Riconoscimento da verificare" : "Annuncio salvato");
    resultRow("Prodotto riconosciuto", data.recognized_product || "Prodotto non identificato con sicurezza");
    resultRow("Offerta salvata", `${data.saved_offer.segment} · ${money(data.saved_offer.price, data.saved_offer.currency)} · ${data.saved_offer.source}`);
    resultRow("Confidenza riconoscimento", `${data.recognition_confidence}%`);
    resultRow("Confidenza descrizione", `${data.description_confidence}%`);
    resultRow("Scatti", data.extracted.shutter_count);
    resultRow("Fattura", data.extracted.invoice_available);
    resultRow("Scatola originale", data.extracted.original_box_available);
    resultRow("Difetti", data.extracted.defects.length ? data.extracted.defects.map(item => item.description).join(", ") : "Nessuno rilevato");
    resultRow("Rischi", data.warnings.join(", ") || "Nessun rischio strutturato rilevato");
    if (data.listing_analysis) {
        resultRow("Valutazione di questo annuncio", data.listing_analysis.recommendation);
        resultRow("Confidenza valutazione", `${data.listing_analysis.confidence}%`);
    }
    resultRow("Offerte attive per il prodotto", data.active_offer_count);
    resultRow("Confronto offerte", data.comparison_available ? "Disponibile" : "Aggiungi un’altra offerta per confrontare");
    if (data.plausible_candidates.length) resultRow("Prodotti possibili", data.plausible_candidates.map(item => item.name).join(", "));
    if (data.association_listing?.needs_review) {
        const associate = document.createElement("button");
        associate.type = "button";
        associate.textContent = "Associa prodotto";
        associate.addEventListener("click", () => openProductAssociation(data.association_listing, result => {
            resultRow("Associazione", `Annuncio associato a ${result.product_name}`);
            actionLink("Apri prodotto", result.product_url, true);
            if (result.comparison_available) actionLink("Confronta offerte", `${result.product_url}&offers=${result.listing_id}#confronta`, true);
        }));
        manualResult.append(associate);
    }
    actionLink("Apri prodotto", data.actions?.open_product, true);
    actionLink("Confronta offerte", data.actions?.compare_offers, data.comparison_available);
    actionLink("Analizza dettagli", data.actions?.analyze_details);
    const again = document.createElement("button");
    again.type = "button";
    again.textContent = "Aggiungi un altro annuncio";
    again.addEventListener("click", () => {
        manualForm.reset();
        document.getElementById("manual-currency").value = "EUR";
        document.getElementById("manual-country").value = "IT";
        manualResult.replaceChildren();
        document.getElementById("manual-url").focus();
    });
    manualResult.append(again);
}

manualOpen.addEventListener("click", () => { manualPanel.hidden = false; document.getElementById("manual-url").focus(); });
manualClose.addEventListener("click", closeManual);
document.addEventListener("keydown", event => { if (event.key === "Escape" && !manualPanel.hidden) closeManual(); });
manualForm.addEventListener("submit", async event => {
    event.preventDefault();
    manualBusy = true;
    manualResult.replaceChildren();
    document.querySelectorAll(".field-error").forEach(item => { item.textContent = ""; });
    const form = new FormData(manualForm);
    const payload = {
        url: form.get("url"), source_name: form.get("source_name"), title: form.get("title"),
        description: form.get("description"), price: form.get("price"),
        currency: String(form.get("currency")).toUpperCase(),
        source_country: String(form.get("source_country")).toUpperCase(),
        segment: form.get("segment"), detected_at: form.get("detected_at") || null,
    };
    try {
        const response = await fetch("/api/listings/manual", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
        const data = await response.json();
        if (!response.ok) {
            const field = document.getElementById(`error-${data.error.field}`);
            if (field) field.textContent = data.error.message;
            else resultRow("Errore", data.error.message);
            return;
        }
        renderSuccess(data);
        await loadContext();
        await loadProducts();
    } finally { manualBusy = false; }
});
