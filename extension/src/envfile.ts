import * as fs from "node:fs";
import * as fsp from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import { assertHostAllowed } from "./compat";
import { log } from "./log";
import { getRuntimePython } from "./runtime";

const MANAGED_KEYS = [
  "CHAT_COMPRESSOR_PYTHON",
  "CHAT_COMPRESSOR_STATE_DIR",
  "K_MAX",
  "GRAPH_FLUSH_EVERY",
  "CHAT_COMPRESSOR_FORWARD_BUDGET",
  "CHAT_COMPRESSOR_INJECT_P1",
] as const;

const FORBIDDEN_KEY = "CURSOR_" + "API_KEY";

export function envPath(): string {
  return path.join(os.homedir(), ".cursor", "chat-compressor.env");
}

export async function projectEnvFile(context: vscode.ExtensionContext): Promise<void> {
  assertHostAllowed();
  const cfg = vscode.workspace.getConfiguration("chatCompressor");
  const python = getRuntimePython() ?? "";
  const stateDir =
    (cfg.get<string>("stateDir") || "").trim() ||
    path.join(os.homedir(), ".cursor", "context-graphs");
  const values: Record<string, string> = {
    CHAT_COMPRESSOR_PYTHON: python,
    CHAT_COMPRESSOR_STATE_DIR: stateDir,
    K_MAX: String(cfg.get<number>("kMax", 32)),
    GRAPH_FLUSH_EVERY: String(cfg.get<number>("graphFlushEvery", 5)),
    CHAT_COMPRESSOR_FORWARD_BUDGET: String(cfg.get<number>("forwardBudget", 1024)),
    CHAT_COMPRESSOR_INJECT_P1: cfg.get<boolean>("injectP1", false) ? "1" : "",
  };

  const dest = envPath();
  await fsp.mkdir(path.dirname(dest), { recursive: true });
  const existing = fs.existsSync(dest) ? await fsp.readFile(dest, "utf8") : "";
  const next = mergeEnvContent(existing, values);
  await fsp.writeFile(dest, next, "utf8");
  log.info(`env projected: ${dest}`);
  void context; // reserved for future storage-relative paths
}

export async function openEnvFile(): Promise<void> {
  assertHostAllowed();
  const dest = envPath();
  if (!fs.existsSync(dest)) {
    await fsp.mkdir(path.dirname(dest), { recursive: true });
    await fsp.writeFile(dest, "", "utf8");
  }
  const doc = await vscode.workspace.openTextDocument(dest);
  await vscode.window.showTextDocument(doc);
}

/** Quote values that would break bash `source` (spaces, quotes, #, empty). */
export function formatEnvValue(value: string): string {
  if (value === "" || /[\s#"']/.test(value)) {
    return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
  }
  return value;
}

/** Pure merge for tests: preserve unmanaged lines; never write Cursor API keys. */
export function mergeEnvContent(
  existing: string,
  managed: Record<string, string>
): string {
  const lines = existing.split(/\r?\n/);
  const out: string[] = [];
  const seen = new Set<string>();

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) {
      out.push(line);
      continue;
    }
    const key = trimmed.split("=", 1)[0]?.trim() ?? "";
    if (key === FORBIDDEN_KEY) {
      // Drop any accidental API key line; never re-emit.
      continue;
    }
    if ((MANAGED_KEYS as readonly string[]).includes(key)) {
      if (!seen.has(key)) {
        out.push(`${key}=${formatEnvValue(managed[key] ?? "")}`);
        seen.add(key);
      }
      continue;
    }
    out.push(line);
  }

  for (const key of MANAGED_KEYS) {
    if (!seen.has(key)) {
      out.push(`${key}=${formatEnvValue(managed[key] ?? "")}`);
      seen.add(key);
    }
  }

  let text = out.join("\n");
  if (!text.endsWith("\n")) {
    text += "\n";
  }
  if (text.includes(`${FORBIDDEN_KEY}=`)) {
    throw new Error("invariant violated: Cursor API key must not appear in projected env");
  }
  return text;
}
