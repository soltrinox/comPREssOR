
export const env = {
  uriScheme: "cursor",
  appName: "Cursor",
  appHost: "desktop",
  remoteName: undefined as string | undefined,
};

export const window = {
  createOutputChannel: () => ({
    appendLine: () => undefined,
    show: () => undefined,
  }),
  showWarningMessage: async () => undefined,
  showErrorMessage: async () => undefined,
  showInformationMessage: async () => undefined,
  withProgress: async (_opts: unknown, task: (p: { report: (v: unknown) => void }) => Promise<unknown>) =>
    task({ report: () => undefined }),
};

export const workspace = {
  getConfiguration: () => ({
    get: (_key: string, def?: unknown) => def,
  }),
  onDidChangeConfiguration: () => ({ dispose: () => undefined }),
  workspaceFolders: undefined as unknown,
  openTextDocument: async () => ({}),
};

export const commands = {
  executeCommand: async () => undefined,
  registerCommand: (_id: string, _fn: unknown) => ({ dispose: () => undefined }),
};

export const extensions = {
  getExtension: () => undefined,
};

export const ProgressLocation = { Notification: 15 };

export default {
  env,
  window,
  workspace,
  commands,
  extensions,
  ProgressLocation,
};
