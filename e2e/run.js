"use strict";

const { mkdtempSync, rmSync } = require("fs");
const { tmpdir } = require("os");
const { join, resolve } = require("path");
const { spawn } = require("child_process");
const http = require("http");
const net = require("net");

const root = resolve(__dirname, "..");
const external = Boolean(process.env.E2E_BASE_URL);
let runtime = null;
let server = null;
let serverOutput = "";

function freePort() {
  return new Promise((resolvePort, reject) => {
    const probe = net.createServer();
    probe.unref();
    probe.on("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const port = probe.address().port;
      probe.close(() => resolvePort(port));
    });
  });
}

function healthy(baseURL) {
  return new Promise(resolveReady => {
    const request = http.get(`${baseURL}/api/status`, response => {
      response.resume();
      resolveReady(response.statusCode === 200);
    });
    request.on("error", () => resolveReady(false));
    request.setTimeout(500, () => { request.destroy(); resolveReady(false); });
  });
}

async function waitForServer(baseURL) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    if (server && server.exitCode !== null) throw new Error(`Dashboard exited early.\n${serverOutput}`);
    if (await healthy(baseURL)) return;
    await new Promise(resolveWait => setTimeout(resolveWait, 100));
  }
  throw new Error(`Dashboard did not become healthy.\n${serverOutput}`);
}

async function main() {
  let exitCode = 1;
  try {
    let baseURL = process.env.E2E_BASE_URL;
    if (!external) {
      const port = await freePort();
      baseURL = `http://127.0.0.1:${port}`;
      runtime = mkdtempSync(join(tmpdir(), "pmi-e2e-"));
      server = spawn(
        "python3", ["-m", "src.dashboard.server", "--demo", "--port", String(port)],
        { cwd: root, env: { ...process.env, PMI_DATA_DIR: runtime }, stdio: ["ignore", "pipe", "pipe"] },
      );
      server.stdout.on("data", chunk => { serverOutput += chunk; });
      server.stderr.on("data", chunk => { serverOutput += chunk; });
      await waitForServer(baseURL);
    }
    exitCode = await new Promise(resolveExit => {
      const test = spawn(
        process.platform === "win32" ? "npx.cmd" : "npx",
        ["playwright", "test", "-c", "e2e/playwright.config.js"],
        { cwd: root, env: { ...process.env, E2E_BASE_URL: baseURL }, stdio: "inherit" },
      );
      test.on("exit", code => resolveExit(code == null ? 1 : code));
    });
  } finally {
    if (server) server.kill("SIGTERM");
    if (runtime) rmSync(runtime, { recursive: true, force: true });
  }
  process.exitCode = exitCode;
}

main().catch(error => { console.error(error); process.exitCode = 1; });
