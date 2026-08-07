"use strict";

const { test, expect } = require("../fixtures/test");
const { submitListing } = require("../helpers/listings");

test.describe("ACCESSIBILITY, MOBILE, AND COARSE PERFORMANCE", () => {
  test("major controls have names, labels, headings, and table headers", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Photo Market Intelligence");
    await expect(page.getByLabel("Cerca prodotto")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Principale" })).toBeVisible();
    await page.goto("/compare.html?ids=sony-alpha-a7-iv,nikon-z6-iii");
    await expect(page.locator("table caption")).toHaveText("Prodotti selezionati");
    expect(await page.locator("table th").count()).toBeGreaterThan(2);
  });

  test("KEYBOARD-ONLY USER opens and closes primary panels with focus restoration", async ({ page }) => {
    await page.goto("/");
    const manual = page.getByRole("button", { name: "Aggiungi annuncio" });
    await manual.focus(); await page.keyboard.press("Enter");
    await expect(page.locator("#manual-url")).toBeFocused();
    await page.keyboard.press("Escape"); await expect(manual).toBeFocused();
    const assistant = page.getByRole("button", { name: "Assistente" });
    await assistant.focus(); await page.keyboard.press("Enter");
    await expect(page.locator("#assistant-close")).toBeFocused();
    await page.locator("#assistant-close").press("Enter"); await expect(assistant).toBeFocused();
  });

  test("keyboard comparison selection updates the selection", async ({ page, request }) => {
    await submitListing(request, { title: "Sony A7 III one", description: "Sony A7 III used", price: "900" });
    await submitListing(request, { title: "Sony A7 III two", description: "Sony A7 III used", price: "850" });
    await page.goto("/product.html?id=sony-alpha-a7-iii");
    const boxes = page.locator(".offer-select input");
    await boxes.nth(0).focus(); await page.keyboard.press("Space");
    await boxes.nth(1).focus(); await page.keyboard.press("Space");
    await expect(page.locator("#selection-status")).toHaveText("2 offerte selezionate");
  });

  test("empty Wishlist and Decisioni states remain honest", async ({ page }) => {
    await page.route("/api/wishlist", route => route.fulfill({ json: { items: [] } }));
    await page.route("/api/decisions", route => route.fulfill({ json: { items: [] } }));
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Wishlist", exact: true }).click();
    await expect(page.locator("#data-list")).toHaveText("Nessun elemento disponibile.");
    await page.locator("#data-close").click();
    await page.locator("header").getByRole("button", { name: "Decisioni", exact: true }).click();
    await expect(page.locator("#data-list")).toHaveText("Nessun elemento disponibile.");
  });

  test("MOBILE USER completes critical navigation and panel flows", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Trova il prodotto e scegli l’offerta migliore" })).toBeVisible();
    await page.getByLabel("Cerca prodotto").fill("A7 IV");
    await page.getByRole("button", { name: "Cerca", exact: true }).click();
    await page.locator(".product-card").filter({ hasText: "Sony Alpha A7 IV" }).getByRole("link", { name: "Apri prodotto" }).click();
    await expect(page.locator("#workspace-header")).toBeVisible();
    await page.getByRole("button", { name: "Assistente" }).click();
    await expect(page.locator("#assistant-panel")).toBeVisible();
    await page.locator("#assistant-close").click();
  });

  test("Home and search become usable within generous smoke thresholds", async ({ page }) => {
    const started = Date.now();
    await page.goto("/");
    await expect(page.getByLabel("Cerca prodotto")).toBeVisible({ timeout: 10_000 });
    expect(Date.now() - started).toBeLessThan(10_000);
    await page.getByLabel("Cerca prodotto").fill("A7IV");
    await page.getByRole("button", { name: "Cerca", exact: true }).click();
    await expect(page.locator("#products")).toContainText("Sony Alpha A7 IV", { timeout: 5_000 });
  });

  test("Annunci with 200 records remains interactable", async ({ page, request }) => {
    const now = new Date().toISOString();
    const items = Array.from({ length: 200 }, (_, index) => ({
      listing_id: index.toString(16).padStart(32, "0"), title: `Performance offer ${index}`,
      segment: "USED", price: 50 + index, currency: "EUR", active: true,
      source: "Fixture Market", country: "IT", shutter_count: null,
      warranty_status: "Garanzia non specificata", last_seen: now,
      product_id: "helios-44-2-58mm-f2", product_name: "Helios 44-2 58mm f/2",
      product_url: "/product.html?id=helios-44-2-58mm-f2", url: "https://example.invalid/fixture",
      needs_review: false, recognition_confidence: 90,
      automatic_recognition: { product_name: "Helios 44-2 58mm f/2", confidence: 90, candidates: [] },
      manual_association: null,
    }));
    await page.route("/api/listings", route => route.fulfill({ json: { items, count: items.length } }));
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Annunci", exact: true }).click();
    await expect(page.locator("#data-close")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("#data-list .listing-card")).toHaveCount(200, { timeout: 15_000 });
    await expect(page.locator("#data-list .listing-card").first()).toBeVisible({ timeout: 15_000 });
  });

  test("blank Annunci filters do not break the listing view", async ({ page, request }) => {
    await submitListing(request, { title: "Sony A7 III filter check", description: "Sony A7 III usata", price: "900" });
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Annunci", exact: true }).click();
    await page.getByRole("button", { name: "Applica filtri" }).click();
    await expect(page.locator("#data-list .listing-card").first()).toBeVisible();
  });
});
