"use strict";

const { test, expect } = require("../fixtures/test");
const { listing, openManualPanel, fillManualForm, submitListing } = require("../helpers/listings");

test.describe("ERROR-PRONE AND SECURITY USERS", () => {
  const invalidCases = [
    ["invalid URL", { url: "not-a-url" }, "url"],
    ["embedded URL credentials", { url: "https://user:pass@example.invalid/item" }, "url"],
    ["invalid price", { price: "abc" }, "price"],
    ["negative price", { price: "-1" }, "price"],
    ["invalid country", { source_country: "ITALY" }, "source_country"],
    ["invalid currency", { currency: "EURO" }, "currency"],
  ];

  for (const [name, changes, field] of invalidCases) {
    test(`rejects ${name}`, async ({ request }) => {
      const response = await request.post("/api/listings/manual", { data: listing(changes) });
      expect(response.status()).toBe(400);
      expect((await response.json()).error.field).toBe(field);
    });
  }

  test("duplicate listing updates rather than duplicates", async ({ request }) => {
    const payload = listing({ title: "Sony A7 IV duplicate check" });
    const first = await request.post("/api/listings/manual", { data: payload });
    const second = await request.post("/api/listings/manual", { data: payload });
    expect(first.ok()).toBeTruthy(); expect(second.ok()).toBeTruthy();
    const one = await first.json(); const two = await second.json();
    expect(two.listing_id).toBe(one.listing_id);
  });

  test("HTML-like and script-like text is rendered as text", async ({ page }) => {
    await openManualPanel(page);
    await fillManualForm(page, { title: "<img src=x onerror=alert(1)> Sony A7 IV", description: "<script>alert(1)</script> Sony A7 IV", price: "1250" });
    await page.locator("#manual-submit").click();
    await expect(page.locator("#manual-result")).toContainText("Offerta salvata");
    expect(await page.locator("script").count()).toBeGreaterThan(0);
    await page.locator("#manual-close").click();
    await page.locator("header").getByRole("button", { name: "Annunci", exact: true }).click();
    await expect(page.locator("#data-list")).toContainText("<img src=x onerror=alert(1)>");
    await expect(page.locator("#data-list img[src='x']")).toHaveCount(0);
  });

  test("malformed and unknown query keys return structured errors", async ({ request }) => {
    const malformed = await request.get("/api/products?confidence_min=not-a-number");
    const unknown = await request.get("/api/products?api_key=secret");
    expect(malformed.status()).toBe(400); expect(unknown.status()).toBe(400);
    expect((await unknown.json()).error.code).toBe("invalid_query");
  });

  test("invalid Host and Origin are rejected for mutations", async ({ request }) => {
    const payload = listing();
    const badHost = await request.post("/api/listings/manual", { data: payload, headers: { Host: "evil.invalid" } });
    const badOrigin = await request.post("/api/listings/manual", { data: payload, headers: { Origin: "https://evil.invalid" } });
    expect(badHost.status()).toBe(400);
    expect(badOrigin.status()).toBe(403);
  });

  test("unsupported mutation method and excessive body are rejected", async ({ request }) => {
    const unsupported = await request.put("/api/listings/manual", { data: {} });
    expect(unsupported.status()).toBeGreaterThanOrEqual(400);
    const oversized = await request.post("/api/listings/manual", {
      headers: { "Content-Type": "application/json" },
      data: { padding: "x".repeat(262_200) },
    });
    expect(oversized.status()).toBe(413);
  });
});
