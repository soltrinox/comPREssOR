import * as fs from "node:fs";
import * as fsp from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import { assertHostAllowed } from "./compat";
import { log } from "./log";
import { ensureRuntime, getRuntimePython } from "./runtime";

const HOOK_EVENTS = [
  "beforeSubmitPrompt",
  "afterAgentResponse",
  "preCompact",
  "sessionStart",
] as const;

const SHIM_REL = "./hooks/chat-compressor.sh";

export async function installUserHooks(context: vscode.ExtensionContext): Promise<void> {
  assertHostAllowed();
  const python = getRuntimePython() ?? (await ensureRuntime(context));
  const cursorDir = path.join(os.homedir(), ".cursor");
  const hooksDir = path.join(cursorDir, "hooks");
  const shimDest = path.join(hooksDir, "chat-compressor.sh");
  const hooksJson = path.join(cursorDir, "hooks.json");

  await fsp.mkdir(hooksDir, { recursive: true });

  const shimSrc = path.join(context.extensionPath, "resources", "hooks", "chat-compressor.sh");
  const shimFallback = path.join(
    context.extensionPath,
    "..",
    "engine",
    "hooks",
    "chat-compressor.sh"
  );
  const src = fs.existsSync(shimSrc) ? shimSrc : shimFallback;
  const body = await fsp.readFile(src, "utf8");
  await fsp.writeFile(shimDest, body, { mode: 0o755 });
  await fsp.chmod(shimDest, 0o755);
  log.info(`shim installed: ${shimDest}`);

  // Ensure env points at provisioned python (envfile also writes this).
  process.env.CHAT_COMPRESSOR_PYTHON = python;

  await mergeHooksJson(hooksJson, SHIM_REL);
}

export async function installProjectHooks(context: vscode.ExtensionContext): Promise<void> {
  assertHostAllowed();
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    throw new Error("No workspace folder open for project hooks.");
  }
  const dest = path.join(folder.uri.fsPath, ".cursor", "hooks.json");
  const templateSrc = path.join(
    context.extensionPath,
    "resources",
    "ide",
    "project-hooks.template.json"
  );
  const fallback = path.join(
    context.extensionPath,
    "..",
    "engine",
    "ide",
    "project-hooks.template.json"
  );
  const src = fs.existsSync(templateSrc) ? templateSrc : fallback;
  await fsp.mkdir(path.dirname(dest), { recursive: true });
  if (fs.existsSync(dest)) {
    // Merge into existing project hooks rather than clobber.
    await mergeHooksJson(dest, SHIM_REL);
  } else {
    await fsp.copyFile(src, dest);
    log.info(`project hooks written: ${dest}`);
  }
}

export async function deployAssets(context: vscode.ExtensionContext): Promise<void> {
  assertHostAllowed();
  const cursorDir = path.join(os.homedir(), ".cursor");
  const ruleSrc = resolveResource(
    context,
    path.join("ide", "rules", "chat-compressor.mdc"),
    path.join("ide", "rules", "chat-compressor.mdc")
  );
  const skillSrc = resolveResource(
    context,
    path.join("ide", "skills", "chat-compressor", "SKILL.md"),
    path.join("ide", "skills", "chat-compressor", "SKILL.md")
  );

  const ruleDest = path.join(cursorDir, "rules", "chat-compressor.mdc");
  const skillDest = path.join(cursorDir, "skills", "chat-compressor", "SKILL.md");
  await fsp.mkdir(path.dirname(ruleDest), { recursive: true });
  await fsp.mkdir(path.dirname(skillDest), { recursive: true });
  await fsp.copyFile(ruleSrc, ruleDest);
  await fsp.copyFile(skillSrc, skillDest);
  log.info(`assets deployed: rule=${ruleDest} skill=${skillDest}`);
}

function resolveResource(
  context: vscode.ExtensionContext,
  underResources: string,
  underEngine: string
): string {
  const a = path.join(context.extensionPath, "resources", underResources);
  if (fs.existsSync(a)) {
    return a;
  }
  return path.join(context.extensionPath, "..", "engine", underEngine);
}

/**
 * Port of install-ide.sh merge filter:
 * drop only entries whose command contains "chat-compressor"; keep everything else.
 * Atomic write via temp + rename; timestamped .bak on first modification.
 */
export async function mergeHooksJson(
  destPath: string,
  command: string = SHIM_REL
): Promise<void> {
  assertHostAllowed();

  let data: Record<string, unknown> = {};
  let existed = false;
  if (fs.existsSync(destPath)) {
    existed = true;
    try {
      data = JSON.parse(await fsp.readFile(destPath, "utf8")) as Record<string, unknown>;
    } catch {
      data = {};
    }
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    data = {};
  }
  if (data.version === undefined) {
    data.version = 1;
  }
  let hooks = data.hooks;
  if (typeof hooks !== "object" || hooks === null || Array.isArray(hooks)) {
    hooks = {};
    data.hooks = hooks;
  }
  const hooksObj = hooks as Record<string, unknown>;
  const entry = { command };

  for (const event of HOOK_EVENTS) {
    const lst = hooksObj[event];
    const arr = Array.isArray(lst) ? [...lst] : [];
    const kept: unknown[] = [];
    for (const item of arr) {
      if (!item || typeof item !== "object") {
        kept.push(item);
        continue;
      }
      const cmd = String((item as { command?: unknown }).command ?? "");
      if (cmd.includes("chat-compressor")) {
        continue;
      }
      kept.push(item);
    }
    kept.push({ ...entry });
    hooksObj[event] = kept;
  }

  if (existed) {
    const bak = `${destPath}.bak.${stamp()}`;
    if (!fs.existsSync(bak)) {
      await fsp.copyFile(destPath, bak);
      log.info(`hooks backup: ${bak}`);
    }
  }

  const tmp = `${destPath}.tmp.${process.pid}`;
  await fsp.writeFile(tmp, JSON.stringify(data, null, 2) + "\n", "utf8");
  await fsp.rename(tmp, destPath);
  log.info(`merged hooks -> ${destPath}`);
}

/** Pure merge helper for unit tests. */
export function mergeCompressorHooks(
  input: unknown,
  command: string = SHIM_REL
): Record<string, unknown> {
  let data: Record<string, unknown> = {};
  if (input && typeof input === "object" && !Array.isArray(input)) {
    data = { ...(input as Record<string, unknown>) };
  }
  if (data.version === undefined) {
    data.version = 1;
  }
  let hooks = data.hooks;
  if (typeof hooks !== "object" || hooks === null || Array.isArray(hooks)) {
    hooks = {};
  } else {
    hooks = { ...(hooks as Record<string, unknown>) };
  }
  data.hooks = hooks;
  const hooksObj = hooks as Record<string, unknown>;
  for (const event of HOOK_EVENTS) {
    const lst = hooksObj[event];
    const arr = Array.isArray(lst) ? [...lst] : [];
    const kept: unknown[] = [];
    for (const item of arr) {
      if (!item || typeof item !== "object") {
        kept.push(item);
        continue;
      }
      const cmd = String((item as { command?: unknown }).command ?? "");
      if (cmd.includes("chat-compressor")) {
        continue;
      }
      kept.push(item);
    }
    kept.push({ command });
    hooksObj[event] = kept;
  }
  return data;
}

function stamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-` +
    `${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  );
}
