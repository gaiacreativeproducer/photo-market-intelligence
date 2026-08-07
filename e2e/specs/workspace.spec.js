"use strict";

const { test, expect } = require("../fixtures/test");
const { submitListing } = require("../helpers/listings");

test.describe("CORE PRODUCT WORKSPACE", () => {
  test("every catalog product page loads without JavaScript errors", async ({ page, request }) => {
    const products = (await (await request.get("/api/products")).json()).products;
    expect(products).toHaveLength(34);
    for (const product of products) {
      await page.goto(`/product.html?id=${product.id}`);
      await expect(page.locator("#title")).toHaveText(product.display_name);
    }
  });

  test("zero-offer product remains usable and does not invent observations", async ({ page }) => {
    await page.goto("/product.html?id=sony-fe-50mm-f1-8");
    await expect(page.locator("#identity")).toContainText("Offerte attive: 0");
    await expect(page.locator("#market-section")).toContainText("Nessun dato di mercato disponibile");
    await expect(page.locator("#listings .listing-card")).toHaveCount(0);
  });

  test("A7 IV BUYER sees two offers and coherent ownership insufficiency", async ({ page, request }) => {
    const fresh = await submitListing(request, { title: "Sony A7 IV nuova", description: "Sony A7 IV nuova con garanzia 24 mesi", price: "1595", segment: "NEW" });
    const used = await submitListing(request, { title: "Sony A7 IV usata", description: "Sony A7 IV usata, 60000 scatti, senza garanzia", price: "1200", segment: "USED" });
    expect(fresh.response.ok()).toBeTruthy(); expect(used.response.ok()).toBeTruthy();
    await page.goto(`/product.html?id=sony-alpha-a7-iv&offers=${fresh.body.listing_id},${used.body.listing_id}#confronta`);
    await expect(page.locator("#listings")).toContainText("Sony A7 IV nuova");
    await expect(page.locator("#listings")).toContainText("Sony A7 IV usata");
    await expect(page.locator("#comparison-table")).toContainText(/395,00\s*€/);
    await expect(page.locator("#comparison-table")).toContainText("24.8%");
    await expect(page.locator("#conclusion")).toContainText(/conclus|dati|verifica/i);
    await expect(page.locator("#ownership")).toContainText(/INSUFFICIENT_DATA|non disponibile/i);
  });

  test("offer count and lowest NEW/USED prices match visible offers", async ({ page, request }) => {
    const id = "sigma-24-70mm-f2-8-dg-dn-ii-art";
    const fresh = await submitListing(request, { title: "Sigma 24-70 II nuovo", description: "Sigma 24-70 II nuovo garanzia 24 mesi", price: "1050", segment: "NEW" });
    const used = await submitListing(request, { title: "Sigma 24-70 II usato", description: "Sigma 24-70 II usato in ottime condizioni", price: "850", segment: "USED" });
    const detail = await (await request.get(`/api/products/${id}`)).json();
    expect(detail.workspace.active_offers.some(item => item.listing_id === fresh.body.listing_id)).toBeTruthy();
    expect(detail.workspace.active_offers.some(item => item.listing_id === used.body.listing_id)).toBeTruthy();
    await page.goto(`/product.html?id=${id}`);
    await expect(page.locator("#listings")).toContainText("Sigma 24-70 II nuovo");
    await expect(page.locator("#listings")).toContainText("Sigma 24-70 II usato");
    await expect(page.locator("#listings")).toContainText(/1050,00\s*€/);
    await expect(page.locator("#listings")).toContainText(/850,00\s*€/);
  });

  test("same-segment comparison remains factual", async ({ page, request }) => {
    const first = await submitListing(request, { title: "Sony A7 III usata uno", description: "Sony A7 III usata", price: "900" });
    const second = await submitListing(request, { title: "Sony A7 III usata due", description: "Sony A7 III usata", price: "850" });
    await page.goto(`/product.html?id=sony-alpha-a7-iii&offers=${first.body.listing_id},${second.body.listing_id}#confronta`);
    await expect(page.locator("#comparison-table")).toContainText(/50,00\s*€/);
    await expect(page.locator("#comparison-table")).toContainText("Confronto fattuale");
  });

  test("cross-currency ownership comparison is blocked honestly", async ({ page, request }) => {
    const fresh = await submitListing(request, { title: "Nikon Z6 III nuova", description: "Nikon Z6 III nuova", price: "2100", currency: "EUR", segment: "NEW" });
    const used = await submitListing(request, { title: "Nikon Z6 III used", description: "Nikon Z6 III used", price: "1700", currency: "USD", segment: "USED", source_country: "US" });
    await page.goto(`/product.html?id=nikon-z6-iii&offers=${fresh.body.listing_id},${used.body.listing_id}#confronta`);
    await expect(page.locator("#comparison-table")).toContainText("valute diverse");
    await expect(page.locator("#comparison-table")).toContainText("Confronto proprietà non disponibile");
  });

  test("original offer links are safe and are not followed", async ({ page, request }) => {
    await submitListing(request, { title: "Sony A7 V nuova", description: "Sony A7 V nuova", segment: "NEW", price: "3000" });
    await page.goto("/product.html?id=sony-alpha-a7-v");
    const link = page.getByRole("link", { name: "Apri originale" }).first();
    await expect(link).toHaveAttribute("href", /^https:\/\/example\.invalid/);
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  test("50 offers render within a coarse regression timeout", async ({ page, request }) => {
    test.setTimeout(120_000);
    for (let index = 0; index < 50; index += 1) {
      const result = await submitListing(request, { title: `Sony FE 50mm f/1.8 offer ${index}`, description: "Sony FE 50mm f/1.8 usato", price: String(100 + index) });
      expect(result.response.ok()).toBeTruthy();
    }
    await page.goto("/product.html?id=sony-fe-50mm-f1-8", { timeout: 15_000 });
    await expect(page.locator("#listings .listing-card")).toHaveCount(50, { timeout: 10_000 });
  });
});
