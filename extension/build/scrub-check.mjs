#!/usr/bin/env node
/**
 * Scrub gate: fail on absolute home path prefixes, personal gmail domains,
 * or Cursor API key assignment lines in tracked source under the repo.
 *
 * Personal machine username must not appear in published sources, except when
 * it is only present as part of allowlisted public hostnames / URLs (lab sites).
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

/** Public lab / product hostnames (URL or bare host); username substring elsewhere still fails. */
const ALLOWED_PUBLIC_HOSTS = [
  "rosariocyber.com",
  "www.rosariocyber.com",
  "eni6ma.com",
  "www.eni6ma.com",
];

/**
 * Strip allowlisted hosts and http(s) URLs to those hosts so hostname matches
 * do not trip the personal-username gate. Does not blanket-allow the username.
 */
function stripAllowedPublicHosts(line) {
  let out = line;
  for (const host of ALLOWED_PUBLIC_HOSTS) {
    const escaped = host.replace(/\./g, "\\.");
    // Full URL first, then bare hostname (markdown link text, etc.).
    out = out.replace(new RegExp(`https?:\\/\\/${escaped}`, "gi"), "");
    out = out.replace(new RegExp(`\\b${escaped}\\b`, "gi"), "");
  }
  return out;
}

function lineHasForbiddenUsername(line) {
  return stripAllowedPublicHosts(line).includes(usernameNeedle);
}

const patterns = [
  { name: "home-Users-prefix", regex: usersNeedle },
  { name: "gmail-domain", regex: gmailNeedle },
  { name: "cursor-api-key-assignment", regex: keyNeedle },
  { name: "personal-username", regex: usernameNeedle, filterLine: lineHasForbiddenUsername },
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
    let hits = r.stdout.trim();
    if (typeof ptn.filterLine === "function") {
      const kept = hits
        .split("\n")
        .filter((line) => {
          // rg -n format: path:lineno:content — filter on content only
          const idx = line.indexOf(":");
          if (idx < 0) return ptn.filterLine(line);
          const idx2 = line.indexOf(":", idx + 1);
          const content = idx2 >= 0 ? line.slice(idx2 + 1) : line;
          return ptn.filterLine(content);
        });
      if (kept.length === 0) {
        console.log(`[PASS] scrub-check: no ${ptn.name} (allowlisted public hosts only)`);
        continue;
      }
      hits = kept.join("\n");
    }
    console.error(`[FAIL] scrub-check: found ${ptn.name}:\n${hits}`);
    failed = true;
  } else if (r.status === 2) {
    console.error(`[FAIL] scrub-check: rg error for ${ptn.name}: ${r.stderr}`);
    failed = true;
  } else {
    console.log(`[PASS] scrub-check: no ${ptn.name}`);
  }
}

process.exit(failed ? 1 : 0);
