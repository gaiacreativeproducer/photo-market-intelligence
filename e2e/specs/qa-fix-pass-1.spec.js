"use strict";

const { test, expect } = require("../fixtures/test");
const { submitListing } = require("../helpers/listings");

test.describe("QA FIX PASS 1", () => {
  test("blank optional filters are omitted and text filters are trimmed", async ({ page, request }) => {
    await submitListing(request, { title: "Sony A7 III serialization", description: "Sony A7 III usata", price: "900" });
    let filteredURL = null;
    page.on("request", value => {
      if (value.url().includes("/api/listings?")) filteredURL = new URL(value.url());
    });
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Annunci", exact: true }).click();
    await page.locator("#data-filters input[name='source']").fill("  E2E Market  ");
    await page.getByRole("button", { name: "Applica filtri" }).click();
    await expect.poll(() => filteredURL && filteredURL.searchParams.get("source")).toBe("E2E Market");
    expect(filteredURL.searchParams.has("price_min")).toBeFalsy();
    expect(filteredURL.searchParams.has("price_max")).toBeFalsy();
    expect(filteredURL.searchParams.has("product_id")).toBeFalsy();
  });

  test("backend still rejects a genuinely invalid numeric filter", async ({ request }) => {
    const response = await request.get("/api/listings?price_min=not-a-number");
    expect(response.status()).toBe(400);
    expect((await response.json()).error.message).toContain("price_min must be numeric");
  });

  test("structured server error is readable and preserves rendered listings", async ({ page, request }) => {
    await submitListing(request, { title: "Sony A7 III preserved", description: "Sony A7 III usata", price: "850" });
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Annunci", exact: true }).click();
    await expect(page.locator("#data-list .listing-card").first()).toBeVisible();
    const before = await page.locator("#data-list .listing-card").count();
    page.allowConsoleError(/status of 400/);
    await page.route("**/api/listings?*", route => route.fulfill({
      status: 400, contentType: "application/json",
      body: JSON.stringify({ error: { code: "invalid_query", message: "Filtro non valido." } }),
    }));
    await page.locator("#data-filters input[name='price_min']").fill("invalid");
    await page.getByRole("button", { name: "Applica filtri" }).click();
    await expect(page.getByRole("alert")).toHaveText("Filtro non valido.");
    await expect(page.locator("#data-list .listing-card")).toHaveCount(before);
  });

  test("malformed API error is safe and a later successful filter recovers", async ({ page, request }) => {
    await submitListing(request, { title: "Sony A7 III recovery", description: "Sony A7 III usata", price: "800" });
    let attempts = 0;
    page.allowConsoleError(/status of 500/);
    await page.route("**/api/listings?*", async route => {
      attempts += 1;
      if (attempts === 1) {
        await route.fulfill({ status: 500, contentType: "text/plain", body: "unexpected" });
      } else {
        await route.continue();
      }
    });
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Annunci", exact: true }).click();
    await page.locator("#data-filters input[name='source']").fill("E2E Market");
    await page.getByRole("button", { name: "Applica filtri" }).click();
    await expect(page.getByRole("alert")).toHaveText("Richiesta non riuscita (500).");
    await page.getByRole("button", { name: "Applica filtri" }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.locator("#data-list .listing-card").first()).toBeVisible();
  });

  test("internal product links stay in-tab while marketplace links stay external", async ({ page, request }) => {
    await submitListing(request, { title: "Sony A7 III links", description: "Sony A7 III usata", price: "750" });
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Annunci", exact: true }).click();
    const card = page.locator("#data-list .listing-card").filter({ hasText: "Sony A7 III links" });
    const internal = card.getByRole("link", { name: /Apri prodotto/ });
    const external = card.getByRole("link", { name: "Apri originale" });
    await expect(internal).not.toHaveAttribute("target", "_blank");
    await expect(external).toHaveAttribute("target", "_blank");
    await expect(external).toHaveAttribute("rel", "noopener noreferrer");
    await internal.click();
    await expect(page.locator("#workspace-header")).toBeVisible();
  });

  test("primary controls and comparison page use consistent Italian copy", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", "it");
    await expect(page.getByText("Filtri e ordinamento", { exact: true })).toBeVisible();
    await expect(page.getByText("Decisioni recenti", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Chiudi", includeHidden: true })).toHaveCount(5);
    await page.goto("/compare.html?ids=sony-alpha-a7-iv,nikon-z6-iii");
    await expect(page.getByRole("heading", { name: "Confronto prodotti" })).toBeVisible();
    await expect(page.locator("table caption")).toHaveText("Prodotti selezionati");
    await expect(page.getByRole("button", { name: "Assistente" })).toBeVisible();
  });
});
