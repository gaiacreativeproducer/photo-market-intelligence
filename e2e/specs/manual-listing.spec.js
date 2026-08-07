"use strict";

const { test, expect } = require("../fixtures/test");
const { fillManualForm, openManualPanel, submitListing } = require("../helpers/listings");

test.describe("MANUAL LISTING AND PRODUCT ASSOCIATION", () => {
  const matrix = [
    ["60k shutter", { title: "Sony A7 IV usata", description: "Sony A7 IV con 60.000 scatti", price: "1200" }, "60000"],
    ["cracked lens", { title: "Sigma 24-70 II", description: "Sigma 24-70 II con lente frontale crepata", price: "500" }, "crepat"],
    ["fungus", { title: "Sigma 24-70 Art", description: "Sigma 24-70 prima generazione con fungus", price: "400" }, "fungus"],
    ["cosmetic scratch", { title: "Sony A7 III", description: "Sony A7 III con piccolo graffio sulla scocca, perfettamente funzionante", price: "700" }, "graffio"],
    ["multiple accessories", { title: "Sony A7 IV", description: "Sony A7 IV con due batterie originali, caricatore Sony e borsa Lowepro", price: "1300" }, "batter"],
  ];

  for (const [name, overrides, expected] of matrix) {
    test(`extracts and persists ${name}`, async ({ request }) => {
      const result = await submitListing(request, overrides);
      expect(result.response.ok()).toBeTruthy();
      expect(JSON.stringify(result.body).toLowerCase()).toContain(expected);
      const listings = await (await request.get("/api/listings")).json();
      expect(listings.items.some(item => item.listing_id === result.body.listing_id)).toBeTruthy();
    });
  }

  test("AMBIGUOUS LISTING USER completes the manual override lifecycle", async ({ page, request }) => {
    const created = await submitListing(request, { title: "Mirrorless camera body", description: "Fotocamera mirrorless usata in buone condizioni", price: "800" });
    expect(created.body.status).toBe("needs_review");
    const listingId = created.body.listing_id;
    const before = (await (await request.get("/api/listings?review=true")).json()).items.find(item => item.listing_id === listingId);
    expect(before).toBeTruthy();
    const firstSeen = before.first_seen_at;

    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Annunci", exact: true }).click();
    const card = page.locator("#data-list .listing-card").filter({ hasText: "Mirrorless camera body" });
    await card.getByRole("button", { name: "Associa prodotto" }).click();
    await page.locator("#association-search").fill("A7 IV");
    await page.locator("#association-search-form").getByRole("button", { name: "Cerca" }).click();
    await page.locator(".association-candidate").filter({ hasText: "Sony Alpha A7 IV" }).getByRole("button", { name: "Associa questo prodotto" }).click();
    await expect(page.locator("#association-status")).toContainText("Annuncio associato a Sony Alpha A7 IV");

    let listing = (await (await request.get("/api/listings")).json()).items.find(item => item.listing_id === listingId);
    expect(listing.needs_review).toBeFalsy();
    expect(listing.first_seen_at).toBe(firstSeen);
    expect(listing.automatic_recognition).toEqual(before.automatic_recognition);

    let response = await request.post(`/api/listings/${listingId}/product`, { data: { product_id: "nikon-z6-iii" } });
    expect(response.ok()).toBeTruthy();
    listing = (await (await request.get("/api/listings")).json()).items.find(item => item.listing_id === listingId);
    expect(listing.product_id).toBe("nikon-z6-iii");
    response = await request.post(`/api/listings/${listingId}/product`, { data: { product_id: null } });
    expect(response.ok()).toBeTruthy();
    listing = (await (await request.get("/api/listings?review=true")).json()).items.find(item => item.listing_id === listingId);
    expect(listing).toBeTruthy();
    expect(listing.first_seen_at).toBe(firstSeen);
  });

  test("manual association rejects an unknown catalog product", async ({ request }) => {
    const created = await submitListing(request, { title: "Unknown camera", description: "Unknown camera body", price: "500" });
    const response = await request.post(`/api/listings/${created.body.listing_id}/product`, { data: { product_id: "not-in-catalog" } });
    expect(response.status()).toBe(400);
    expect((await response.json()).error.code).toBe("unknown_product");
  });

  test("manual form refreshes the dashboard immediately", async ({ page }) => {
    await openManualPanel(page);
    await fillManualForm(page, { title: "Panasonic Lumix S5 II nuova", description: "Panasonic Lumix S5 II nuova con garanzia", price: "1400", segment: "NEW" });
    await page.locator("#manual-submit").click();
    await expect(page.locator("#manual-result")).toContainText("Annuncio salvato");
    await expect(page.locator("#live-count")).not.toHaveText("0");
    await expect(page.locator("#manual-result").getByRole("link", { name: "Apri prodotto" })).toBeVisible();
  });
});
