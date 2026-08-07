"use strict";

const { test, expect } = require("../fixtures/test");

test.describe("EBAY BROWSE REFRESH", () => {
  test("successful mocked refresh updates offers without navigation", async ({ page }) => {
    await page.goto("/product.html?id=sony-fe-50mm-f1-8");
    const originalURL = page.url();
    const detail = await (await page.request.get("/api/products/sony-fe-50mm-f1-8")).json();
    const offer = {
      listing_id: "ebay-mocked", product_id: "sony-fe-50mm-f1-8", product_name: "Sony FE 50mm f/1.8",
      title: "Sony FE 50mm f/1.8 eBay", source: "eBay", segment: "USED", price: 125, currency: "EUR",
      country: "IT", marketplace: "EBAY_IT", condition: "Usato", original_condition: "Used",
      buying_options: ["FIXED_PRICE"], auction: false, shipping_cost: 8, shipping_currency: "EUR",
      shutter_count: null, warranty_status: "Non disponibile", defects: [], accessories: [],
      recognition_confidence: 92, description_confidence: 70, missing_information_count: 1,
      missing_information: ["warranty status"], url: "https://www.ebay.it/itm/123",
      automatic_recognition: {product_name: "Sony FE 50mm f/1.8", confidence: 92}, manual_association: null,
    };
    detail.workspace.active_offers = [offer];
    detail.workspace.offer_count = 1;
    await page.route("**/api/products/sony-fe-50mm-f1-8/ebay-refresh", route => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({environment:"SANDBOX",retrieved:3,recognized:2,persisted_relevant:2,ignored_accessory_unmatched:1,needs_review:0,results_retrieved:3,relevant_offers_added:2,existing_offers_updated:0,ignored_results:1,connector_errors:[],workspace:detail.workspace}),
    }));
    await page.getByRole("button", {name:"Aggiorna offerte eBay"}).click();
    await expect(page.locator("#ebay-refresh-status")).toContainText("eBay SANDBOX: 3 recuperati, 2 riconosciuti, 2 pertinenti, 1 accessori/non riconosciuti ignorati, 0 da verificare");
    await expect(page.locator("#listings")).toContainText("Sony FE 50mm f/1.8 eBay");
    await expect(page.locator("#listings")).toContainText("EBAY_IT");
    expect(page.url()).toBe(originalURL);
  });

  test("refresh errors and Production authorization are readable and secret-free", async ({ page }) => {
    await page.goto("/product.html?id=sony-fe-50mm-f1-8");
    page.allowConsoleError(/status of 502/);
    await page.route("**/api/products/sony-fe-50mm-f1-8/ebay-refresh", route => route.fulfill({
      status: 502, contentType: "application/json",
      body: JSON.stringify({error:{code:"ebay_connector_error",message:"eBay Production Browse access is not enabled for this application."}}),
    }));
    await page.getByRole("button", {name:"Aggiorna offerte eBay"}).click();
    await expect(page.locator("#ebay-refresh-status")).toHaveText("eBay Production Browse access is not enabled for this application.");
    const text = await page.locator("body").innerText();
    expect(text).not.toContain("PMI_EBAY_CLIENT_SECRET");
    expect(text).not.toContain("Bearer ");
  });
});
