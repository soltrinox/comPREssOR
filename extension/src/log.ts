import * as vscode from "vscode";

let channel: vscode.OutputChannel | undefined;

function getChannel(): vscode.OutputChannel {
  if (!channel) {
    channel = vscode.window.createOutputChannel("comPREssOR");
  }
  return channel;
}

function stamp(): string {
  return new Date().toISOString();
}

export const log = {
  info(msg: string): void {
    getChannel().appendLine(`[INFO ${stamp()}] ${msg}`);
  },
  warn(msg: string): void {
    getChannel().appendLine(`[WARN ${stamp()}] ${msg}`);
  },
  error(msg: string): void {
    getChannel().appendLine(`[ERROR ${stamp()}] ${msg}`);
  },
};

export function showLog(): void {
  getChannel().show(true);
}
