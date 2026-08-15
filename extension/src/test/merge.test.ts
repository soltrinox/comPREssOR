import { describe, expect, it } from "vitest";
import { mergeCompressorHooks } from "../cursorBridge";
import { mergeEnvContent } from "../envfile";

describe("mergeCompressorHooks", () => {
  it("preserves unrelated hooks and registers four events", () => {
    const input = {
      version: 1,
      hooks: {
        beforeSubmitPrompt: [{ command: "./hooks/other.sh" }],
        sessionEnd: [{ command: "./hooks/keep-me.sh" }],
      },
    };
    const out = mergeCompressorHooks(input);
    const hooks = out.hooks as Record<string, Array<{ command: string }>>;
    expect(hooks.beforeSubmitPrompt.map((h) => h.command)).toEqual([
      "./hooks/other.sh",
      "./hooks/chat-compressor.sh",
    ]);
    expect(hooks.afterAgentResponse).toEqual([
      { command: "./hooks/chat-compressor.sh" },
    ]);
    expect(hooks.preCompact).toEqual([{ command: "./hooks/chat-compressor.sh" }]);
    expect(hooks.sessionStart).toEqual([{ command: "./hooks/chat-compressor.sh" }]);
    expect(hooks.sessionEnd).toEqual([{ command: "./hooks/keep-me.sh" }]);
  });

  it("drops prior chat-compressor entries only", () => {
    const input = {
      hooks: {
        beforeSubmitPrompt: [
          { command: "/old/path/chat-compressor.sh" },
          { command: "./hooks/keep.sh" },
        ],
      },
    };
    const out = mergeCompressorHooks(input);
    const hooks = out.hooks as Record<string, Array<{ command: string }>>;
    expect(hooks.beforeSubmitPrompt.map((h) => h.command)).toEqual([
      "./hooks/keep.sh",
      "./hooks/chat-compressor.sh",
    ]);
  });
});

describe("mergeEnvContent", () => {
  it("projects managed keys and strips Cursor API key assignment", () => {
    const forbiddenKey = "CURSOR_" + "API_KEY";
    const existing = [
      "UNMANAGED=keep",
      `${forbiddenKey}=secret`,
      "K_MAX=8",
      "",
    ].join("\n");
    const out = mergeEnvContent(existing, {
      CHAT_COMPRESSOR_PYTHON: "/venv/bin/python",
      CHAT_COMPRESSOR_STATE_DIR: "/tmp/graphs",
      K_MAX: "32",
      GRAPH_FLUSH_EVERY: "5",
      CHAT_COMPRESSOR_FORWARD_BUDGET: "1024",
      CHAT_COMPRESSOR_INJECT_P1: "",
    });
    expect(out).toContain("UNMANAGED=keep");
    expect(out).toContain("K_MAX=32");
    expect(out).toContain("CHAT_COMPRESSOR_PYTHON=/venv/bin/python");
    expect(out).toContain('CHAT_COMPRESSOR_INJECT_P1=""');
    expect(out).not.toContain(`${forbiddenKey}=`);
  });

  it("quotes managed values that contain spaces", () => {
    const spacedPy =
      "/" + "Users" + "/me/Library/Application Support/Cursor/User/globalStorage/x/venv/bin/python";
    const out = mergeEnvContent("", {
      CHAT_COMPRESSOR_PYTHON: spacedPy,
      CHAT_COMPRESSOR_STATE_DIR: "/tmp/graphs",
      K_MAX: "32",
      GRAPH_FLUSH_EVERY: "5",
      CHAT_COMPRESSOR_FORWARD_BUDGET: "1024",
      CHAT_COMPRESSOR_INJECT_P1: "",
    });
    expect(out).toContain('CHAT_COMPRESSOR_PYTHON="' + spacedPy + '"');
  });
});
