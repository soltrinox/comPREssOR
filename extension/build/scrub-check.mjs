#!/usr/bin/env node
/**
 * Scrub gate: fail on absolute home path prefixes, personal gmail domains,
 * or Cursor API key assignment lines in tracked source under the repo.
 */
import { spawnSync } from "node:child_process";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");

// Construct needles so this file itself does not contain the forbidden literals.
const usersNeedle = "/" + "Users" + "/";
const gmailNeedle = "@" + "gmail";
const keyNeedle = "CURSOR_" + "API_KEY=";
// Personal machine username must not appear in published sources.
const usernameNeedle = "rosa" + "rio";

const patterns = [
  { name: "home-Users-prefix", regex: usersNeedle },
  { name: "gmail-domain", regex: gmailNeedle },
  { name: "cursor-api-key-assignment", regex: keyNeedle },
  { name: "personal-username", regex: usernameNeedle },
];

const globs = [
  "--glob", "!**/node_modules/**",
  "--glob", "!**/.venv/**",
  "--glob", "!**/dist/**",
  "--glob", "!**/resources/**",
  "--glob", "!**/.git/**",
  "--glob", "!**/test-results/**",
  "--glob", "!**/*.vsix",
  "--glob", "!**/build/scrub-check.mjs",
];

let failed = false;
for (const ptn of patterns) {
  const r = spawnSync("rg", ["-n", "--fixed-strings", ptn.regex, repoRoot, ...globs], {
    encoding: "utf8",
  });
  if (r.status === 0 && r.stdout.trim()) {
    console.error(`[FAIL] scrub-check: found ${ptn.name}:\n${r.stdout}`);
    failed = true;
  } else if (r.status === 2) {
    console.error(`[FAIL] scrub-check: rg error for ${ptn.name}: ${r.stderr}`);
    failed = true;
  } else {
    console.log(`[PASS] scrub-check: no ${ptn.name}`);
  }
}

process.exit(failed ? 1 : 0);
