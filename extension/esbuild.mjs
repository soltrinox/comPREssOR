import * as esbuild from "esbuild";

const watch = process.argv.includes("--watch");

const common = {
  bundle: true,
  platform: "node",
  target: "node20",
  external: ["vscode"],
  sourcemap: true,
  logLevel: "info",
};

async function main() {
  const ctxExt = await esbuild.context({
    ...common,
    entryPoints: ["src/extension.ts"],
    outfile: "dist/extension.js",
    format: "cjs",
  });
  const ctxUn = await esbuild.context({
    ...common,
    entryPoints: ["src/uninstall.ts"],
    outfile: "dist/uninstall.js",
    format: "cjs",
  });

  if (watch) {
    await Promise.all([ctxExt.watch(), ctxUn.watch()]);
  } else {
    await Promise.all([ctxExt.rebuild(), ctxUn.rebuild()]);
    await Promise.all([ctxExt.dispose(), ctxUn.dispose()]);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
