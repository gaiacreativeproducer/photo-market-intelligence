"use strict";

const { test, expect } = require("../fixtures/test");

const searches = [
  ["A7IV", "Sony Alpha A7 IV"],
  ["A7 IV", "Sony Alpha A7 IV"],
  ["ILCE-7M4", "Sony Alpha A7 IV"],
  ["Sigma 24-70 II", "Sigma 24-70mm f/2.8 DG DN II Art"],
  ["sigma 24-70 ii", "Sigma 24-70mm f/2.8 DG DN II Art"],
  ["night walker", "Sirui Night Walker 35mm T1.2 S35"],
  ["70-200", "70-200"],
];

test.describe("SEARCH-HEAVY USER", () => {
  for (const [query, expected] of searches) {
    test(`finds catalog product for ${query}`, async ({ page }) => {
      await page.goto("/");
      await page.getByLabel("Cerca prodotto").fill(query);
      await page.getByRole("button", { name: "Cerca", exact: true }).click();
      await expect(page.locator("#products")).toContainText(expected);
    });
  }

  test("reports a nonexistent product honestly", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Cerca prodotto").fill("nonexistent product xyz");
    await page.getByRole("button", { name: "Cerca", exact: true }).click();
    await expect(page.locator("#message")).toHaveText("Nessun prodotto corrisponde alla ricerca.");
  });

  test("empty search restores the full catalog", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Cerca prodotto").fill("A7IV");
    await page.getByRole("button", { name: "Cerca", exact: true }).click();
    await page.getByLabel("Cerca prodotto").fill("");
    await page.getByRole("button", { name: "Cerca", exact: true }).click();
    await expect(page.locator("#message")).toHaveText("34 prodotti");
  });

  test("rapid searches settle on the latest query", async ({ page }) => {
    await page.goto("/");
    for (const query of ["A7", "Sigma", "ILCE-7M4"]) {
      await page.getByLabel("Cerca prodotto").fill(query);
      await page.getByRole("button", { name: "Cerca", exact: true }).click();
    }
    await expect(page.locator("#products")).toContainText("Sony Alpha A7 IV");
  });
});
