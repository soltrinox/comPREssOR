import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as fsp from "node:fs/promises";
import * as path from "node:path";
import * as vscode from "vscode";
import { assertHostAllowed } from "./compat";
import { log } from "./log";

const WHEEL_STATE_KEY = "chatCompressor.wheelVersion";
const PKG_VERSION = "0.1.0";

let cachedPython: string | undefined;

export function getRuntimePython(): string | undefined {
  return cachedPython;
}

export interface EnsureRuntimeOptions {
  force?: boolean;
}

export async function ensureRuntime(
  context: vscode.ExtensionContext,
  opts: EnsureRuntimeOptions = {}
): Promise<string> {
  assertHostAllowed();

  const venvDir = path.join(context.globalStorageUri.fsPath, "venv");
  const venvPython = path.join(
    venvDir,
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
  );
  const wheelVersion = `${PKG_VERSION}`;
  const prev = context.globalState.get<string>(WHEEL_STATE_KEY);

  if (!opts.force && prev === wheelVersion && fs.existsSync(venvPython)) {
    cachedPython = venvPython;
    log.info(`runtime idempotent: ${venvPython}`);
    return venvPython;
  }

  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "comPREssOR: provisioning Python runtime",
      cancellable: false,
    },
    async (progress) => {
      progress.report({ message: "discovering interpreter" });
      const base = await discoverInterpreter();
      await fsp.mkdir(context.globalStorageUri.fsPath, { recursive: true });

      if (!fs.existsSync(venvPython)) {
        progress.report({ message: "creating venv" });
        await run(base, ["-m", "venv", venvDir], context.globalStorageUri.fsPath);
      }

      const wheel = await findBundledWheel(context);
      progress.report({ message: "installing wheel" });
      await run(venvPython, ["-m", "pip", "install", "--upgrade", "pip"], venvDir);
      await run(venvPython, ["-m", "pip", "install", "--force-reinstall", wheel], venvDir);

      // Sanity: hook CLI help
      await run(venvPython, ["-m", "chat_compressor.hook_cli", "--help"], venvDir);

      await context.globalState.update(WHEEL_STATE_KEY, wheelVersion);
      cachedPython = venvPython;
      log.info(`runtime ready: ${venvPython}`);
      return venvPython;
    }
  );
}

async function discoverInterpreter(): Promise<string> {
  const cfg = vscode.workspace.getConfiguration("chatCompressor");
  const setting = (cfg.get<string>("pythonPath") || "").trim();
  const candidates: string[] = [];
  if (setting) {
    candidates.push(setting);
  }

  try {
    const pyExt = vscode.extensions.getExtension("ms-python.python");
    if (pyExt) {
      if (!pyExt.isActive) {
        await pyExt.activate();
      }
      const api = pyExt.exports as {
        settings?: { getExecutionDetails?: () => { execCommand?: string[] } };
      };
      const exec = api?.settings?.getExecutionDetails?.()?.execCommand?.[0];
      if (exec) {
        candidates.push(exec);
      }
    }
  } catch {
    // ignore python extension probe failures
  }

  candidates.push("python3", "python");

  for (const c of candidates) {
    try {
      const ver = await probeVersion(c);
      if (ver && versionOk(ver)) {
        log.info(`using interpreter ${c} (${ver.join(".")})`);
        return c;
      }
      if (ver) {
        log.warn(`rejecting ${c}: Python ${ver.join(".")} < 3.11`);
      }
    } catch (err) {
      log.warn(`probe failed for ${c}: ${String(err)}`);
    }
  }
  throw new Error("No Python >= 3.11 found. Set chatCompressor.pythonPath.");
}

function versionOk(v: [number, number]): boolean {
  return v[0] > 3 || (v[0] === 3 && v[1] >= 11);
}

function probeVersion(bin: string): Promise<[number, number] | null> {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, ["-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    child.stdout.on("data", (d) => {
      out += String(d);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        resolve(null);
        return;
      }
      const m = out.trim().match(/^(\d+)\.(\d+)/);
      if (!m) {
        resolve(null);
        return;
      }
      resolve([Number(m[1]), Number(m[2])]);
    });
  });
}

async function findBundledWheel(context: vscode.ExtensionContext): Promise<string> {
  const resources = path.join(context.extensionPath, "resources");
  const entries = await fsp.readdir(resources).catch(() => [] as string[]);
  const wheel = entries.find((e) => e.endsWith(".whl") && e.startsWith("chat_compressor"));
  if (!wheel) {
    throw new Error(`No chat_compressor wheel in ${resources}. Build with npm run build.`);
  }
  return path.join(resources, wheel);
}

function run(bin: string, args: string[], cwd: string): Promise<void> {
  return new Promise((resolve, reject) => {
    log.info(`$ ${bin} ${args.join(" ")}`);
    const child = spawn(bin, args, { cwd, stdio: ["ignore", "pipe", "pipe"] });
    child.stdout.on("data", (d) => log.info(String(d).trimEnd()));
    child.stderr.on("data", (d) => log.warn(String(d).trimEnd()));
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${bin} ${args.join(" ")} exited ${code}`));
      }
    });
  });
}
