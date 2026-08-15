import { describe, expect, it } from "vitest";
import { detectHost } from "../compat";

function env(partial: {
  uriScheme?: string;
  appName?: string;
  appHost?: string;
  remoteName?: string;
}) {
  return {
    uriScheme: partial.uriScheme ?? "cursor",
    appName: partial.appName ?? "Cursor",
    appHost: partial.appHost ?? "desktop",
    remoteName: partial.remoteName,
  };
}

describe("detectHost", () => {
  it("allows Cursor desktop local", () => {
    const d = detectHost(env({}) as never);
    expect(d.allowed).toBe(true);
  });

  it("denies vscode uriScheme", () => {
    const d = detectHost(env({ uriScheme: "vscode" }) as never);
    expect(d.allowed).toBe(false);
    expect(d.code).toBe("uriScheme");
  });

  it("denies non-Cursor appName", () => {
    const d = detectHost(env({ appName: "Visual Studio Code" }) as never);
    expect(d.allowed).toBe(false);
    expect(d.code).toBe("appName");
  });

  it("denies remoteName set", () => {
    const d = detectHost(env({ remoteName: "ssh-remote" }) as never);
    expect(d.allowed).toBe(false);
    expect(d.code).toBe("remoteName");
  });

  it("denies non-desktop appHost", () => {
    const d = detectHost(env({ appHost: "desktop" /* ok */ }) as never);
    expect(d.allowed).toBe(true);
    const d2 = detectHost(env({ appHost: "web" }) as never);
    expect(d2.allowed).toBe(false);
    expect(d2.code).toBe("appHost");
  });
});
