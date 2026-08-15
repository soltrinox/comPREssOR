import * as vscode from "vscode";
import { detectHost, type HostDecision } from "./compat";
import { installUserHooks, installProjectHooks, deployAssets } from "./cursorBridge";
import { projectEnvFile, openEnvFile } from "./envfile";
import { log, showLog } from "./log";
import { ensureRuntime, getRuntimePython } from "./runtime";

const DENY_FINGERPRINT_KEY = "chatCompressor.denyFingerprintShown";

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  // REQ-HOST: fail-closed gate is the first statement.
  const decision = detectHost();
  logHostSignals(decision);

  await vscode.commands.executeCommand(
    "setContext",
    "chatCompressor.hostSupported",
    decision.allowed
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("chatCompressor.compatibilityReport", () => {
      showCompatibilityReport(decision);
    })
  );

  if (!decision.allowed) {
    await handleDeny(context, decision);
    // Still register no-op gated commands so package.json enablement stays consistent.
    registerGatedCommands(context, null);
    return;
  }

  registerGatedCommands(context, decision);

  const cfg = vscode.workspace.getConfiguration("chatCompressor");
  try {
    await ensureRuntime(context);
    await projectEnvFile(context);
    if (cfg.get<boolean>("autoInstallHooks", true)) {
      await installUserHooks(context);
      await deployAssets(context);
    }
  } catch (err) {
    log.error(`Activation side-effects failed: ${String(err)}`);
    void vscode.window.showErrorMessage(
      `comPREssOR activation failed: ${err instanceof Error ? err.message : String(err)}`
    );
  }

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(async (e) => {
      if (!e.affectsConfiguration("chatCompressor")) {
        return;
      }
      // Re-check host; never write on deny even if settings change.
      const again = detectHost();
      if (!again.allowed) {
        return;
      }
      try {
        await projectEnvFile(context);
      } catch (err) {
        log.error(`Env re-project failed: ${String(err)}`);
      }
    })
  );
}

/** REQ-UNI: deactivate performs no cleanup. */
export function deactivate(): void {
  // intentionally empty
}

function logHostSignals(decision: HostDecision): void {
  log.info(
    `host decision=${decision.allowed ? "ALLOW" : "DENY"} code=${decision.code ?? "ok"} ` +
      `uriScheme=${decision.signals.uriScheme} appName=${JSON.stringify(decision.signals.appName)} ` +
      `appHost=${decision.signals.appHost} remoteName=${JSON.stringify(decision.signals.remoteName)}`
  );
}

async function handleDeny(
  context: vscode.ExtensionContext,
  decision: HostDecision
): Promise<void> {
  const fingerprint = [
    decision.signals.uriScheme,
    decision.signals.appName,
    decision.signals.appHost,
    decision.signals.remoteName ?? "",
    decision.code ?? "",
  ].join("|");

  const cfg = vscode.workspace.getConfiguration("chatCompressor");
  const strict = cfg.get<boolean>("strictHostGate", true);
  const shown = context.globalState.get<string>(DENY_FINGERPRINT_KEY);

  if (shown === fingerprint) {
    log.info("deny warning suppressed (fingerprint already shown)");
    return;
  }

  await context.globalState.update(DENY_FINGERPRINT_KEY, fingerprint);

  const detail =
    `comPREssOR is Cursor-only. Host denied (${decision.code}). ` +
    `uriScheme=${decision.signals.uriScheme} appName=${decision.signals.appName} ` +
    `appHost=${decision.signals.appHost} remoteName=${decision.signals.remoteName ?? ""}`;

  if (!strict) {
    log.warn(`strictHostGate=false: soft deny UI only — ${detail}`);
    void vscode.window.showWarningMessage(
      "comPREssOR: unsupported host (writes disabled). See Compatibility Report."
    );
    return;
  }

  const pick = await vscode.window.showWarningMessage(
    detail,
    "Uninstall",
    "Details"
  );
  if (pick === "Details") {
    showLog();
    showCompatibilityReport(decision);
  } else if (pick === "Uninstall") {
    await vscode.commands.executeCommand(
      "workbench.extensions.action.uninstallExtension",
      "soltrinox.compressor"
    );
  }
}

function showCompatibilityReport(decision: HostDecision): void {
  showLog();
  log.info("--- Compatibility Report ---");
  log.info(`allowed=${decision.allowed} code=${decision.code ?? "ok"}`);
  log.info(`uriScheme=${decision.signals.uriScheme}`);
  log.info(`appName=${decision.signals.appName}`);
  log.info(`appHost=${decision.signals.appHost}`);
  log.info(`remoteName=${decision.signals.remoteName ?? ""}`);
  log.info(`python=${getRuntimePython() ?? "(not provisioned)"}`);
  void vscode.window.showInformationMessage(
    decision.allowed
      ? "comPREssOR: host ALLOW — see Output → comPREssOR"
      : `comPREssOR: host DENY (${decision.code}) — see Output → comPREssOR`
  );
}

function registerGatedCommands(
  context: vscode.ExtensionContext,
  decision: HostDecision | null
): void {
  const requireAllow = async (fn: () => Promise<void>): Promise<void> => {
    const live = detectHost();
    if (!live.allowed) {
      log.warn("command blocked: host not allowed");
      void vscode.window.showWarningMessage(
        "comPREssOR: command blocked on unsupported host (fail-closed)."
      );
      return;
    }
    await fn();
  };

  context.subscriptions.push(
    vscode.commands.registerCommand("chatCompressor.installHooks", () =>
      requireAllow(async () => {
        await ensureRuntime(context);
        await projectEnvFile(context);
        await installUserHooks(context);
        await deployAssets(context);
        void vscode.window.showInformationMessage("comPREssOR: hooks installed/repaired.");
      })
    ),
    vscode.commands.registerCommand("chatCompressor.installProjectHooks", () =>
      requireAllow(async () => {
        await installProjectHooks(context);
        void vscode.window.showInformationMessage(
          "comPREssOR: project hooks template written (opt-in)."
        );
      })
    ),
    vscode.commands.registerCommand("chatCompressor.showStatus", () =>
      requireAllow(async () => {
        showCompatibilityReport(decision ?? detectHost());
      })
    ),
    vscode.commands.registerCommand("chatCompressor.reprovisionRuntime", () =>
      requireAllow(async () => {
        await ensureRuntime(context, { force: true });
        await projectEnvFile(context);
        void vscode.window.showInformationMessage("comPREssOR: runtime reprovisioned.");
      })
    ),
    vscode.commands.registerCommand("chatCompressor.purgeState", () =>
      requireAllow(async () => {
        const ok = await vscode.window.showWarningMessage(
          "Delete ~/.cursor/context-graphs/? This cannot be undone.",
          { modal: true },
          "Purge"
        );
        if (ok !== "Purge") {
          return;
        }
        const fs = await import("node:fs/promises");
        const os = await import("node:os");
        const path = await import("node:path");
        const root = path.join(os.homedir(), ".cursor", "context-graphs");
        await fs.rm(root, { recursive: true, force: true });
        log.info(`purged ${root}`);
      })
    ),
    vscode.commands.registerCommand("chatCompressor.openEnvFile", () =>
      requireAllow(async () => {
        await openEnvFile();
      })
    )
  );
}
