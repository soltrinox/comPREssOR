/**
 * vscode:uninstall entry (plain Node — no vscode module).
 * Strips compressor hooks + shim + rule + skill.
 * Leaves ~/.cursor/context-graphs/ and chat-compressor.env intact.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const HOOK_EVENTS = [
  "beforeSubmitPrompt",
  "afterAgentResponse",
  "preCompact",
  "sessionStart",
];

function main(): void {
  const cursorDir = path.join(os.homedir(), ".cursor");
  const hooksJson = path.join(cursorDir, "hooks.json");
  const shim = path.join(cursorDir, "hooks", "chat-compressor.sh");
  const rule = path.join(cursorDir, "rules", "chat-compressor.mdc");
  const skillDir = path.join(cursorDir, "skills", "chat-compressor");

  stripHooks(hooksJson);
  rm(shim);
  rm(rule);
  rmDir(skillDir);
  process.stderr.write("[comPREssOR uninstall] stripped hooks/shim/rule/skill\n");
}

function stripHooks(dest: string): void {
  if (!fs.existsSync(dest)) {
    return;
  }
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(fs.readFileSync(dest, "utf8")) as Record<string, unknown>;
  } catch {
    return;
  }
  const hooks = data.hooks;
  if (!hooks || typeof hooks !== "object") {
    return;
  }
  const hooksObj = hooks as Record<string, unknown>;
  for (const event of HOOK_EVENTS) {
    const lst = hooksObj[event];
    if (!Array.isArray(lst)) {
      continue;
    }
    hooksObj[event] = lst.filter((item) => {
      if (!item || typeof item !== "object") {
        return true;
      }
      const cmd = String((item as { command?: unknown }).command ?? "");
      return !cmd.includes("chat-compressor");
    });
  }
  const tmp = `${dest}.tmp.uninstall`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + "\n", "utf8");
  fs.renameSync(tmp, dest);
}

function rm(p: string): void {
  try {
    if (fs.existsSync(p)) {
      fs.unlinkSync(p);
    }
  } catch {
    // best-effort
  }
}

function rmDir(p: string): void {
  try {
    fs.rmSync(p, { recursive: true, force: true });
  } catch {
    // best-effort
  }
}

main();
