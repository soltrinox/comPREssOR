import * as vscode from "vscode";

/** Host deny reasons (REQ-HOST). */
export type HostDenyCode =
  | "uriScheme"
  | "appName"
  | "appHost"
  | "remoteName"
  | "unknown";

export interface HostSignals {
  uriScheme: string;
  appName: string;
  appHost: string;
  remoteName: string | undefined;
}

export interface HostDecision {
  allowed: boolean;
  code?: HostDenyCode;
  signals: HostSignals;
}

/**
 * Fail-closed Cursor host gate.
 * Literal allow values from Phase 0 preflight (docs/PREFLIGHT.md):
 *   uriScheme === "cursor"
 *   appName contains "Cursor"
 *   appHost === "desktop"
 *   remoteName empty/undefined
 */
export function detectHost(
  env: Pick<typeof vscode.env, "uriScheme" | "appName" | "appHost" | "remoteName"> = vscode.env
): HostDecision {
  const signals: HostSignals = {
    uriScheme: env.uriScheme ?? "",
    appName: env.appName ?? "",
    appHost: env.appHost ?? "",
    remoteName: env.remoteName || undefined,
  };

  if (signals.uriScheme !== "cursor") {
    return { allowed: false, code: "uriScheme", signals };
  }
  if (!signals.appName.includes("Cursor")) {
    return { allowed: false, code: "appName", signals };
  }
  if (signals.appHost !== "desktop") {
    return { allowed: false, code: "appHost", signals };
  }
  if (signals.remoteName) {
    return { allowed: false, code: "remoteName", signals };
  }
  return { allowed: true, signals };
}

/** Enforce gate inside bridge/runtime entry points (REQ-CFG-02). */
export function assertHostAllowed(): HostDecision {
  const decision = detectHost();
  if (!decision.allowed) {
    throw new Error(
      `comPREssOR host gate denied (${decision.code}): writes to ~/.cursor are forbidden`
    );
  }
  return decision;
}
