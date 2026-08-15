#!/usr/bin/env node
/**
 * Fail the build if publish target looks like Microsoft Marketplace.
 * REQ-HOST-05: Open VSX only.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pkgPath = path.resolve(__dirname, "..", "package.json");
const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));

const target = (process.env.VSCE_TARGET || process.env.MARKETPLACE_TARGET || "").toLowerCase();

if (
  target &&
  (target.includes("microsoft") ||
    target.includes("vs-marketplace") ||
    target === "marketplace")
) {
  console.error(
    `[FAIL] assert-cursor-target: forbidden publish target '${target}' (Open VSX only)`
  );
  process.exit(1);
}

const scripts = JSON.stringify(pkg.scripts || {});
for (const bad of ["vsce publish", "npx vsce publish"]) {
  if (scripts.includes(bad)) {
    console.error(
      `[FAIL] assert-cursor-target: package.json scripts must not include '${bad}'`
    );
    process.exit(1);
  }
}

for (const envName of ["VSCE_PAT", "VS_MARKETPLACE_TOKEN"]) {
  if (process.env[envName]) {
    console.error(
      `[FAIL] assert-cursor-target: ${envName} is set; Microsoft Marketplace publish is blocked`
    );
    process.exit(1);
  }
}

console.log("[PASS] assert-cursor-target: Open VSX-only publish path");
