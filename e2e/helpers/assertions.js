"use strict";

const { expect } = require("../fixtures/test");

async function expectHealthy(page) {
  const response = await page.request.get("/api/status");
  expect(response.ok()).toBeTruthy();
  expect((await response.json()).status).toBe("OK");
}

async function expectNoPrivateSerial(page) {
  expect((await page.locator("body").innerText()).toLowerCase()).not.toContain("body-a");
  expect((await page.locator("body").innerText()).toLowerCase()).not.toContain("serial_reference");
}

module.exports = { expectHealthy, expectNoPrivateSerial };
