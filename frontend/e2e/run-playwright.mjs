import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const e2eDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(e2eDir, "..");
const rootDir = path.resolve(frontendDir, "..");
const resultDir = path.join(frontendDir, "test-results");
const databasePath = path.join(resultDir, `agro-playwright-${Date.now()}-${process.pid}.sqlite3`);
mkdirSync(resultDir, { recursive: true });

const python = spawnSync(path.join(rootDir, ".venv/bin/python"), [path.join(e2eDir, "prepare-db.py"), databasePath], {
  cwd: rootDir,
  env: { ...process.env, PYTHONPATH: path.join(rootDir, "backend") },
  stdio: "inherit"
});
if (python.status !== 0) process.exit(python.status ?? 1);

const playwright = spawnSync("npx", ["playwright", "test", ...process.argv.slice(2)], {
  cwd: frontendDir,
  env: { ...process.env, AGRO_PLAYWRIGHT_DATABASE_PATH: databasePath },
  stdio: "inherit"
});
process.exit(playwright.status ?? 1);
