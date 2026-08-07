"use strict";

function listing(overrides = {}) {
  const token = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return {
    url: `https://example.invalid/e2e/${token}`,
    source_name: "E2E Market",
    title: "Sony Alpha A7 IV body",
    description: "Sony A7 IV in buone condizioni, fattura e scatola originale.",
    price: "1200",
    currency: "EUR",
    source_country: "IT",
    segment: "USED",
    detected_at: null,
    ...overrides,
  };
}

async function submitListing(request, overrides = {}) {
  const payload = listing(overrides);
  const response = await request.post("/api/listings/manual", { data: payload });
  return { response, payload, body: await response.json() };
}

async function openManualPanel(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Aggiungi annuncio" }).click();
  await page.locator("#manual-url").waitFor();
}

async function fillManualForm(page, overrides = {}) {
  const payload = listing(overrides);
  await page.locator("#manual-url").fill(payload.url);
  await page.locator("#manual-source").fill(payload.source_name);
  await page.locator("#manual-title").fill(payload.title);
  await page.locator("#manual-description").fill(payload.description);
  await page.locator("#manual-price").fill(String(payload.price));
  await page.locator("#manual-currency").fill(payload.currency);
  await page.locator("#manual-country").fill(payload.source_country);
  await page.locator("#manual-segment").selectOption(payload.segment);
  return payload;
}

module.exports = { fillManualForm, listing, openManualPanel, submitListing };
