"use strict";

const { test, expect } = require("../fixtures/test");
const { expectNoPrivateSerial } = require("../helpers/assertions");

test.describe("NAVIGATION PERSONAS", () => {
  test("NEW USER understands primary actions and opens a zero-offer workspace", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Trova il prodotto e scegli l’offerta migliore" })).toBeVisible();
    await page.getByLabel("Cerca prodotto").fill("Sony FE 50mm f/1.8");
    await page.getByRole("button", { name: "Cerca", exact: true }).click();
    await page.locator(".product-card").filter({ hasText: "Sony FE 50mm f/1.8" }).getByRole("link", { name: "Apri prodotto" }).click();
    await expect(page.locator("#listings")).toContainText("Nessuna offerta attiva raccolta");
    await expect(page.locator("#market-section")).toContainText("Nessun dato di mercato disponibile");
  });

  for (const [button, heading] of [["Annunci", "Annunci"], ["Wishlist", "Wishlist"], ["Corredo", "Corredo"], ["Decisioni", "Decisioni"]]) {
    test(`${button} opens an actionable data view`, async ({ page }) => {
      await page.goto("/");
      await page.locator("header").getByRole("button", { name: button, exact: true }).click();
      await expect(page.locator("#data-heading")).toHaveText(heading);
      await expect(page.locator("#data-close")).toBeFocused();
    });
  }

  test("WISHLIST USER reaches a product workspace", async ({ page }) => {
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Wishlist", exact: true }).click();
    const link = page.locator("#data-list").getByRole("link", { name: "Apri prodotto" }).first();
    await expect(link).not.toHaveAttribute("target", "_blank");
    await link.click();
    await expect(page.locator("#workspace-header")).toBeVisible();
  });

  test("INVENTORY USER reaches workspace without private serials", async ({ page }) => {
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Corredo", exact: true }).click();
    await expectNoPrivateSerial(page);
    const link = page.locator("#data-list").getByRole("link", { name: "Apri prodotto" }).first();
    await expect(link).not.toHaveAttribute("target", "_blank");
    await link.click();
    await expectNoPrivateSerial(page);
  });

  test("DECISION HISTORY USER follows a safe product link", async ({ page }) => {
    await page.goto("/");
    await page.locator("header").getByRole("button", { name: "Decisioni", exact: true }).click();
    const link = page.locator("#data-list a").first();
    await expect(link).toHaveAttribute("href", /product\.html\?id=/);
    await expect(link).not.toHaveAttribute("target", "_blank");
    await link.click();
    await expect(page.getByRole("heading", { name: "Conclusione complessiva" })).toBeVisible();
  });

  test("product-local navigation exposes every analysis level", async ({ page }) => {
    await page.goto("/product.html?id=sony-alpha-a7-iv");
    for (const label of ["Offerte", "Confronta offerte", "Mercato", "Analisi", "Nuovo vs usato", "Memoria"]) {
      await expect(page.locator(".workspace-nav").getByRole("link", { name: label, exact: true })).toBeVisible();
    }
  });
});
