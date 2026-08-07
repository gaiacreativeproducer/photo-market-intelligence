"use strict";

const { test: base, expect } = require("@playwright/test");

const ALLOWED_CONSOLE_MESSAGES = [];

const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    const problems = [];
    const expectedProblems = [];
    page.allowConsoleError = pattern => expectedProblems.push({ pattern, seen: false });
    page.on("pageerror", error => problems.push(`pageerror: ${error.message}`));
    page.on("console", message => {
      if (message.type() !== "error") return;
      const expected = expectedProblems.find(item => item.pattern.test(message.text()));
      if (expected) { expected.seen = true; return; }
      if (!ALLOWED_CONSOLE_MESSAGES.some(pattern => pattern.test(message.text()))) {
        problems.push(`console.error: ${message.text()}`);
      }
    });
    page.on("requestfailed", request => {
      const url = request.url();
      if (url.startsWith(testInfo.project.use.baseURL)) {
        problems.push(`requestfailed: ${request.method()} ${url} — ${request.failure()?.errorText}`);
      }
    });
    await use(page);
    const missingExpected = expectedProblems.filter(item => !item.seen).map(item => String(item.pattern));
    expect(missingExpected, "expected console errors were not observed").toEqual([]);
    if (problems.length) {
      await testInfo.attach("browser-errors.txt", {
        body: Buffer.from(problems.join("\n")), contentType: "text/plain",
      });
    }
    expect(problems, "unexpected browser errors").toEqual([]);
  },
});

module.exports = { test, expect };
