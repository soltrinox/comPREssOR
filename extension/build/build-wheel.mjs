#!/usr/bin/env node
/**
 * Build chat-compressor wheel into extension/resources/.
 * resources/ is gitignored and populated at build time.
 */
import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const extRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extRoot, "..");
const engineRoot = path.join(repoRoot, "engine");
const resources = path.join(extRoot, "resources");

function run(cmd, args, cwd) {
  console.log(`$ ${cmd} ${args.join(" ")}`);
  const r = spawnSync(cmd, args, { cwd, stdio: "inherit", shell: false });
  if (r.status !== 0) {
    process.exit(r.status ?? 1);
  }
}

function pickPython() {
  const venvPy = path.join(engineRoot, ".venv", "bin", "python");
  if (fs.existsSync(venvPy)) {
    const r = spawnSync(
      venvPy,
      ["-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
      { encoding: "utf8" }
    );
    if (r.status === 0) {
      const [maj, min] = r.stdout.trim().split(".").map(Number);
      if (maj > 3 || (maj === 3 && min >= 11)) {
        console.log(`[info] using engine venv python: ${venvPy}`);
        return venvPy;
      }
    }
  }
  for (const c of ["python3.12", "python3.11", "python3"]) {
    const r = spawnSync(
      c,
      ["-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
      { encoding: "utf8" }
    );
    if (r.status === 0) {
      const [maj, min] = r.stdout.trim().split(".").map(Number);
      if (maj > 3 || (maj === 3 && min >= 11)) {
        return c;
      }
    }
  }
  console.error("Need Python >= 3.11 to build the wheel (prefer engine/.venv)");
  process.exit(1);
}

fs.mkdirSync(resources, { recursive: true });
for (const f of fs.readdirSync(resources)) {
  if (f.endsWith(".whl")) {
    fs.unlinkSync(path.join(resources, f));
  }
}

const py = pickPython();
run(py, ["-m", "pip", "install", "-q", "build"], engineRoot);
run(py, ["-m", "build", "--wheel", "--outdir", resources], engineRoot);

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(s, d);
    } else if (entry.isFile()) {
      fs.copyFileSync(s, d);
    }
  }
}

copyDir(path.join(engineRoot, "hooks"), path.join(resources, "hooks"));
copyDir(path.join(engineRoot, "ide"), path.join(resources, "ide"));

const wheels = fs.readdirSync(resources).filter((f) => f.endsWith(".whl"));
if (wheels.length === 0) {
  console.error("No wheel produced");
  process.exit(1);
}
console.log(`[PASS] wheel(s): ${wheels.join(", ")}`);
