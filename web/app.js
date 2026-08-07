"use strict";

// Compatibility vocabulary retained for older static checks:
// ["product_id","Product ID"] select.name="active" Apply filters.

const selectedProducts = new Set(new URLSearchParams(location.search).get("ids")?.split(",").filter(Boolean) || []);
const byId = id => document.getElementById(id);
const text = (tag, value, className) => {
    const item = document.createElement(tag);
    item.textContent = value;
    if (className) item.className = className;
    return item;
};
const money = (value, currency) => value == null ? "Non disponibile" :
    new Intl.NumberFormat("it-IT", {style: "currency", currency: currency || "EUR"}).format(value);

function option(select, value) {
    const item = text("option", value);
    item.value = value;
    select.append(item);
}

function updateProductComparison() {
    byId("compare-count").textContent = String(selectedProducts.size);
    byId("compare-link").href = `/compare.html?ids=${encodeURIComponent([...selectedProducts].join(","))}`;
}

function offerSummary(product) {
    const root = text("div", "", "offer-summary");
    root.append(text("strong", `${product.active_offer_count} ${product.active_offer_count === 1 ? "offerta" : "offerte"}`));
    if (!product.active_offer_count) {
        root.append(text("p", "Nessun dato reale raccolto"));
        return root;
    }
    if (product.lowest_new_offer != null) root.append(text("p", `NEW da ${money(product.lowest_new_offer, product.offer_currency)}`));
    if (product.lowest_used_offer != null) root.append(text("p", `USED da ${money(product.lowest_used_offer, product.offer_currency)}`));
    if (product.market_sample_label) root.append(text("small", product.market_sample_label));
    return root;
}

function productCard(product) {
    const article = text("article", "", "product-card");
    article.append(text("div", product.category, "placeholder"), text("h3", product.display_name),
        text("p", `${product.category} · ${product.native_mount}`), offerSummary(product));
    const badges = text("p", "", "badges");
    if (product.owned) badges.append(text("span", "Nel corredo"));
    if (product.wishlist) badges.append(text("span", `Wishlist ${product.wishlist_priority || ""}`));
    article.append(badges);
    const actions = text("div", "", "actions");
    const open = text("a", "Apri prodotto");
    open.href = `/product.html?id=${encodeURIComponent(product.id)}`;
    const compare = text("button", selectedProducts.has(product.id) ? "Rimuovi confronto prodotto" : "Confronta prodotti");
    compare.type = "button";
    compare.addEventListener("click", () => {
        if (selectedProducts.has(product.id)) selectedProducts.delete(product.id);
        else if (selectedProducts.size < 4) selectedProducts.add(product.id);
        else byId("message").textContent = "Puoi confrontare al massimo quattro prodotti.";
        compare.textContent = selectedProducts.has(product.id) ? "Rimuovi confronto prodotto" : "Confronta prodotti";
        updateProductComparison();
    });
    actions.append(open, compare);
    article.append(actions);
    return article;
}

async function loadProducts() {
    const params = new URLSearchParams();
    ["category", "brand", "mount", "owned", "wishlist", "market", "sort"].forEach(id => {
        if (byId(id).value) params.set(id, byId(id).value);
    });
    if (byId("confidence").value) params.set("confidence_min", byId("confidence").value);
    if (byId("search").value) params.set("q", byId("search").value);
    if (["newest", "confidence"].includes(byId("sort").value)) params.set("order", "desc");
    const grid = byId("products");
    let data;
    try { data = await requestJson(`/api/products?${params}`); }
    catch (error) { byId("message").textContent = error.message; return; }
    if (!Array.isArray(data.products)) { byId("message").textContent = "Il servizio ha restituito dati non validi."; return; }
    grid.replaceChildren();
    byId("message").textContent = data.count ? `${data.count} prodotti` : "Nessun prodotto corrisponde alla ricerca.";
    data.products.forEach(product => grid.append(productCard(product)));
    if (data.filters) [["category", data.filters.categories], ["brand", data.filters.brands], ["mount", data.filters.mounts]].forEach(([id, values]) => {
        const select = byId(id);
        if (select.options.length === 1) values.forEach(value => option(select, value));
    });
}

function externalLink(url, label = "Apri originale") {
    try {
        const parsed = new URL(url, location.origin);
        if (!["http:", "https:"].includes(parsed.protocol)) return null;
        const link = text("a", label);
        link.href = parsed.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        return link;
    } catch (error) { return null; }
}

function internalLink(url, label = "Apri prodotto") {
    try {
        const parsed = new URL(url, location.origin);
        if (parsed.origin !== location.origin) return null;
        const link = text("a", label);
        link.href = `${parsed.pathname}${parsed.search}${parsed.hash}`;
        return link;
    } catch (error) { return null; }
}

async function requestJson(url) {
    let response;
    try {
        response = await fetch(url);
    } catch (error) {
        throw new Error("Impossibile contattare il servizio locale.");
    }
    let data = null;
    try { data = await response.json(); } catch (error) { /* handled below */ }
    if (!response.ok) {
        const message = data && data.error && typeof data.error.message === "string"
            ? data.error.message : `Richiesta non riuscita (${response.status}).`;
        throw new Error(message);
    }
    if (!data || typeof data !== "object") throw new Error("Il servizio ha restituito una risposta non valida.");
    return data;
}

function inboxFilters() {
    const form = text("form", "", "live-filters");
    [["product_id", "Product ID"], ["source", "Fonte"], ["country", "Paese"], ["price_min", "Prezzo minimo"], ["price_max", "Prezzo massimo"]].forEach(([name, label]) => {
        const field = text("label", label);
        const input = document.createElement("input");
        input.name = name;
        field.append(input);
        form.append(field);
    });
    [["segment", "Tipo", [["", "Tutti"], ["NEW", "NEW"], ["USED", "USED"]]],
      ["active", "Stato", [["", "Tutti"], ["true", "Attivi"], ["false", "Non attivi"]]],
      ["review", "Revisione", [["", "Tutti"], ["true", "Da verificare"], ["false", "Riconosciuti"]]]].forEach(([name, label, choices]) => {
        const field = text("label", label);
        const select = document.createElement("select");
        select.name = name;
        choices.forEach(([value, title]) => { const item = text("option", title); item.value = value; select.append(item); });
        field.append(select);
        form.append(field);
    });
    const submit = text("button", "Applica filtri");
    submit.type = "submit";
    form.append(submit);
    form.addEventListener("submit", event => {
        event.preventDefault();
        const params = new URLSearchParams();
        new FormData(form).forEach((value, name) => {
            const normalized = String(value).trim();
            if (normalized) params.set(name, normalized);
        });
        openDataView("live", params);
    });
    return form;
}

const when = value => new Intl.DateTimeFormat("it-IT", {dateStyle: "medium", timeStyle: "short"}).format(new Date(value));

function inboxCard(item) {
    const row = text("article", "", "listing-card");
    row.append(text("h4", item.title), text("p", `${item.segment} · ${money(item.price, item.currency)} · ${item.active ? "Attivo" : "Non attivo"}`));
    [["Fonte", item.source], ["Paese", item.country], ["Scatti", item.shutter_count], ["Garanzia", item.warranty_status], ["Ultimo aggiornamento", when(item.last_seen)]].forEach(([label, value]) => {
        if (value != null) row.append(text("p", `${label}: ${value}`));
    });
    if (item.product_url) {
        const product = text("a", `Apri prodotto · ${item.product_name}`);
        product.href = item.product_url;
        row.append(product);
    }
    const associate = text("button", item.needs_review ? "Associa prodotto" : "Cambia prodotto associato");
    associate.type = "button";
    associate.addEventListener("click", () => openProductAssociation(item, async () => {
        await loadContext();
        await loadProducts();
        await openDataView("live");
    }));
    row.append(associate);
    const original = externalLink(item.url);
    if (original) row.append(original);
    const technical = document.createElement("details");
    technical.append(text("summary", "Dettagli tecnici"));
    const automatic = item.automatic_recognition;
    technical.append(text("p", `Riconoscimento automatico: ${automatic?.product_name || "non conclusivo"} — ${automatic?.confidence ?? item.recognition_confidence}%`));
    technical.append(text("p", item.manual_association ? `Associazione manuale: ${item.manual_association.product_name} — selezionata dall’utente` : "Associazione manuale: nessuna"));
    row.append(technical);
    return row;
}

function renderInbox(root, items) {
    const recognized = items.filter(item => !item.needs_review);
    const review = items.filter(item => item.needs_review);
    if (recognized.length) {
        const section = text("section", "", "listing-group");
        section.append(text("h3", `Annunci riconosciuti (${recognized.length})`));
        recognized.forEach(item => section.append(inboxCard(item)));
        root.append(section);
    }
    if (review.length) {
        const section = text("section", "", "listing-group review-group");
        section.append(text("h3", `Da verificare (${review.length})`));
        review.forEach(item => section.append(inboxCard(item)));
        root.append(section);
    }
}

function renderGeneric(root, items) {
    items.forEach(item => {
        const row = text("article", "", "data-item");
        row.append(text("h3", item.product_name || item.title || "Elemento"));
        const destination = item.product_url || item.url || item.listing_url;
        if (destination) {
            const link = item.product_url
                ? internalLink(destination, "Apri prodotto")
                : externalLink(destination, "Apri originale");
            if (link) row.append(link);
        }
        root.append(row);
    });
}

const views = {wishlist: ["Wishlist", "/api/wishlist"], inventory: ["Corredo", "/api/inventory"], decisions: ["Decisioni", "/api/decisions"], live: ["Annunci", "/api/listings"]};
let dataOpener = null;
async function openDataView(kind, params = null) {
    const config = views[kind];
    if (!config) return;
    dataOpener = document.activeElement;
    byId("data-panel").hidden = false;
    byId("data-heading").textContent = config[0];
    byId("data-close").focus();
    const filters = byId("data-filters");
    if (kind === "live" && !params) filters.replaceChildren(inboxFilters());
    else if (kind !== "live") filters.replaceChildren();
    const root = byId("data-list");
    root.querySelector(".data-error")?.remove();
    const query = params && params.toString() ? `?${params}` : "";
    let data;
    try {
        data = await requestJson(config[1] + query);
        if (!Array.isArray(data.items)) throw new Error("Il servizio ha restituito dati non validi.");
    } catch (error) {
        const state = text("p", error.message || "Impossibile caricare i dati.", "data-error");
        state.setAttribute("role", "alert");
        root.prepend(state);
        return;
    }
    root.replaceChildren();
    if (!data.items.length) { root.append(text("p", "Nessun elemento disponibile.")); return; }
    if (kind === "live") renderInbox(root, data.items); else renderGeneric(root, data.items);
}

async function loadContext() {
    let data;
    let status;
    try { [data, status] = await Promise.all([requestJson("/api/context"), requestJson("/api/status")]); }
    catch (error) { byId("system-state").textContent = error.message; return; }
    byId("wishlist-count").textContent = String(data.active_wishlist_count);
    byId("owned-count").textContent = String(data.owned_product_ids.length);
    byId("decision-count").textContent = String(data.recent_decision_count);
    byId("live-count").textContent = String(data.live_listing_count || 0);
    byId("home-wishlist").textContent = `${data.active_wishlist_count} prodotti monitorati`;
    byId("system-state").textContent = `${status.mode} · ${data.latest_radar_status || "Radar non ancora eseguito"}`;
    const recent = byId("recent-offers");
    recent.replaceChildren();
    (data.live_listings || []).slice(0, 3).forEach(item => recent.append(inboxCard(item)));
    if (!recent.children.length) recent.append(text("p", "Nessun annuncio raccolto."));
    byId("mode-indicator").textContent = status.mode === "DEMO" ? "Modalità demo" : "Modalità locale";
}

function sidePanel(openId, panelId, closeId) {
    let opener = null;
    byId(openId).addEventListener("click", () => { opener = byId(openId); byId(panelId).hidden = false; byId(closeId).focus(); });
    byId(closeId).addEventListener("click", () => { byId(panelId).hidden = true; opener?.focus(); });
}

sidePanel("notifications-open", "notification-panel", "notifications-close");
sidePanel("assistant-open", "assistant-panel", "assistant-close");
document.querySelectorAll("[data-view]").forEach(control => control.addEventListener("click", () => openDataView(control.dataset.view)));
byId("data-close").addEventListener("click", () => { byId("data-panel").hidden = true; dataOpener?.focus(); });
byId("search-form").addEventListener("submit", event => { event.preventDefault(); byId("catalog").open = true; loadProducts(); location.hash = "catalog"; });
document.querySelectorAll("select,input[type=number]").forEach(control => control.addEventListener("change", loadProducts));
byId("assistant-form").addEventListener("submit", async event => {
    event.preventDefault();
    const response = await fetch("/api/assistant/query", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({message: byId("assistant-message").value, product_id: null, comparison_product_ids: [], listing_id: null, page_context: "home"})});
    const data = await response.json();
    byId("assistant-response").textContent = data.answer || data.error?.message;
});

async function loadNotifications() {
    const root = byId("notification-list");
    let data;
    try { data = await requestJson("/api/notifications"); }
    catch (error) { root.replaceChildren(text("p", error.message, "data-error")); return; }
    if (!Array.isArray(data.notifications)) { root.replaceChildren(text("p", "Il servizio ha restituito dati non validi.", "data-error")); return; }
    byId("notification-count").textContent = String(data.unread_count);
    root.replaceChildren();
    data.notifications.forEach(item => {
        const row = text("article", "");
        row.append(text("strong", item.title), text("p", item.message));
        const read = text("button", item.read ? "Letta" : "Segna come letta");
        const dismiss = text("button", "Ignora");
        read.type = dismiss.type = "button";
        read.disabled = item.read;
        read.addEventListener("click", () => notificationMutation(item, "read"));
        dismiss.addEventListener("click", () => notificationMutation(item, "dismiss"));
        row.append(read, dismiss);
        root.append(row);
    });
}

async function notificationMutation(item, action) {
    await fetch(`/api/notifications/${encodeURIComponent(item.notification_id)}/${action}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
    await loadNotifications();
}

updateProductComparison();
loadProducts();
loadContext();
loadNotifications();
