"use strict";

let associationListing = null;
let associationChanged = null;
let associationOpener = null;

function associationNode(tag, value, className) {
    const item = document.createElement(tag);
    item.textContent = value;
    if (className) item.className = className;
    return item;
}

function associationCandidate(product, prefix = "") {
    const row = associationNode("article", "", "association-candidate");
    const name = product.display_name || [product.brand, product.model, product.version].filter(Boolean).join(" ");
    row.append(associationNode("h3", `${prefix}${name}`));
    row.append(associationNode("p", `${product.category} · ${product.mount || product.native_mount}`));
    const select = associationNode("button", "Associa questo prodotto");
    select.type = "button";
    select.addEventListener("click", () => saveProductAssociation(product.product_id || product.id));
    row.append(select);
    return row;
}

function renderAssociationResults(candidates, results) {
    const root = document.getElementById("association-results");
    root.replaceChildren();
    const seen = new Set();
    candidates.slice(0, 5).forEach(product => {
        const id = product.product_id || product.id;
        if (!id || seen.has(id)) return;
        seen.add(id);
        root.append(associationCandidate(product, "Suggerito · "));
    });
    results.slice(0, 12).forEach(product => {
        const id = product.product_id || product.id;
        if (!id || seen.has(id)) return;
        seen.add(id);
        root.append(associationCandidate(product));
    });
    if (!root.children.length) root.append(associationNode("p", "Nessun prodotto trovato."));
}

async function searchAssociations(query) {
    if (!query.trim()) { renderAssociationResults(associationListing.automatic_recognition?.candidates || [], []); return; }
    const response = await fetch(`/api/search?q=${encodeURIComponent(query.trim())}`);
    const data = await response.json();
    renderAssociationResults(associationListing.automatic_recognition?.candidates || [], data.products || []);
}

async function saveProductAssociation(productId) {
    const response = await fetch(`/api/listings/${encodeURIComponent(associationListing.listing_id)}/product`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({product_id: productId}),
    });
    const data = await response.json();
    const status = document.getElementById("association-status");
    if (!response.ok) { status.textContent = data.error.message; return; }
    status.textContent = productId ? `Annuncio associato a ${data.product_name}` : "Associazione manuale rimossa.";
    associationListing.manual_association = data.manual_association;
    document.getElementById("association-remove").hidden = !data.manual_association;
    if (associationChanged) associationChanged(data);
}

function openProductAssociation(listing, onChanged) {
    associationListing = listing;
    associationChanged = onChanged;
    associationOpener = document.activeElement;
    const panel = document.getElementById("association-panel");
    panel.hidden = false;
    document.getElementById("association-status").textContent = "";
    document.getElementById("association-remove").hidden = !listing.manual_association;
    renderAssociationResults(listing.automatic_recognition?.candidates || [], []);
    document.getElementById("association-search").value = "";
    document.getElementById("association-search").focus();
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("association-close").addEventListener("click", () => {
        document.getElementById("association-panel").hidden = true;
        associationOpener?.focus();
    });
    document.getElementById("association-search-form").addEventListener("submit", event => {
        event.preventDefault();
        searchAssociations(document.getElementById("association-search").value);
    });
    document.getElementById("association-remove").addEventListener("click", () => saveProductAssociation(null));
});
