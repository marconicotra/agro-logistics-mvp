import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(frontendDir, "..");
const resultDir = path.join(frontendDir, "test-results");
const databasePath = process.env.AGRO_PLAYWRIGHT_DATABASE_PATH
  ? path.resolve(process.env.AGRO_PLAYWRIGHT_DATABASE_PATH)
  : path.join(resultDir, `agro-playwright-${Date.now()}-${process.pid}.sqlite3`);
const databaseUrl = `sqlite+pysqlite:///${databasePath}`;
const qaPhone = "+5491100000001";
const webhookSecret = "playwright-local-only-hmac-secret-2026-10-26";

mkdirSync(resultDir, { recursive: true });
if (!process.env.AGRO_PLAYWRIGHT_DATABASE_PATH) {
  execFileSync(path.join(rootDir, ".venv/bin/python"), [path.join(frontendDir, "e2e/prepare-db.py"), databasePath], {
    cwd: rootDir,
    env: { ...process.env, PYTHONPATH: path.join(rootDir, "backend") },
    stdio: "inherit"
  });
  process.env.AGRO_PLAYWRIGHT_DATABASE_PATH = databasePath;
}

const localBackendEnv = {
  APP_ENV: "local",
  STORAGE_BACKEND: "sql",
  DATABASE_URL: databaseUrl,
  WHATSAPP_PROVIDER: "mock",
  ENABLE_REAL_WHATSAPP: "false",
  WHATSAPP_ALLOWLIST_SOURCE: "env",
  WHATSAPP_ALLOWLIST_DEFAULT_ALLOW: "false",
  WHATSAPP_DEV_ALLOWLIST: qaPhone,
  ENABLE_TEST_ROLE_SWITCHING: "true",
  KAPSO_WEBHOOK_SECRET: webhookSecret,
  KAPSO_TIMESTAMP_TOLERANCE_SECONDS: "3600",
  AI_PROVIDER: "disabled",
  OPENAI_API_KEY: "",
  STT_ENABLED: "false",
  MEDIA_DOWNLOAD_ENABLED: "false",
  GOOGLE_ROUTES_API_KEY: "",
  GOOGLE_MAPS_BROWSER_KEY: "",
  ROUTE_OPERATIONS_ENABLED: "true"
};

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results/results",
  timeout: 90_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: "./playwright-report", open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:5176",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure"
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } }
    },
    {
      name: "mobile-chromium",
      use: { ...devices["iPhone 13"], browserName: "chromium" }
    }
  ],
  webServer: [
    {
      command: ".venv/bin/python frontend/e2e/qa_api.py",
      cwd: rootDir,
      url: "http://127.0.0.1:8004/health",
      reuseExistingServer: false,
      timeout: 30_000,
      env: localBackendEnv
    },
    {
      command: ".venv/bin/python scripts/dispatch_notification_outbox.py --poll-seconds 0.5",
      cwd: rootDir,
      reuseExistingServer: false,
      timeout: 30_000,
      env: localBackendEnv
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5176 --strictPort",
      cwd: frontendDir,
      url: "http://127.0.0.1:5176",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        VITE_API_BASE_URL: "http://127.0.0.1:8004",
        VITE_OPERATOR_USER_ID: "playwright_operator",
        VITE_OPERATOR_ROLE: "admin",
        VITE_SHOW_QA_FIELDS: "true",
        VITE_SUPABASE_URL: "",
        VITE_SUPABASE_ANON_KEY: ""
      }
    }
  ]
});
