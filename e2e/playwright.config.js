const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./specs",
  fullyParallel: false,
  workers: 1,
  timeout: 20_000,
  expect: { timeout: 5_000 },
  reporter: [["line"], ["html", { outputFolder: "../playwright-report", open: "never" }]],
  outputDir: "../test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:8765",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
