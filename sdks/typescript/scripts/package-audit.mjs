import { mkdir, mkdtemp, readFile, readdir, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const sdkRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await mkdtemp(join(tmpdir(), "zebra-sdk-package-audit-"));
const packageSpecs = {
  contracts: ["package/package.json", "package/dist/index.js", "package/dist/index.cjs", "package/dist/index.d.ts"],
  "ui-contracts": ["package/package.json", "package/dist/index.js", "package/dist/index.cjs", "package/dist/index.d.ts"],
  "client-core": ["package/package.json", "package/dist/index.js", "package/dist/index.cjs", "package/dist/index.d.ts"],
  react: [
    "package/package.json",
    "package/README.md",
    "package/dist/index.js",
    "package/dist/index.cjs",
    "package/dist/index.d.ts",
    "package/styles.css",
    "package/styles/surfaces.css",
  ],
};

await run("pnpm", ["build"], sdkRoot);
for (const [packageDirectory, requiredEntries] of Object.entries(packageSpecs)) {
  const packDirectory = join(workspace, packageDirectory);
  await mkdir(packDirectory, { recursive: true });
  await run(
    "pnpm",
    ["pack", "--pack-destination", packDirectory],
    join(sdkRoot, "packages", packageDirectory),
  );
  const tarballs = (await readdir(packDirectory)).filter((entry) => entry.endsWith(".tgz"));
  if (tarballs.length !== 1) throw new Error(`${packageDirectory}: expected one tarball`);
  const tarball = join(packDirectory, tarballs[0]);
  const entries = (await capture("tar", ["-tzf", tarball], sdkRoot))
    .trim()
    .split("\n")
    .filter(Boolean)
    .sort();
  const required = [...requiredEntries].sort();
  if (JSON.stringify(entries) !== JSON.stringify(required)) {
    throw new Error(`${packageDirectory}: unexpected package contents\n${entries.join("\n")}`);
  }
  await run("tar", ["-xzf", tarball, "-C", packDirectory], sdkRoot);
  await auditExtractedPackage(packageDirectory, join(packDirectory, "package"));
}

console.log("SDK package audit passed: allowlist, exports, secrets, paths and source boundaries");

async function auditExtractedPackage(label, root) {
  const manifest = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
  if (manifest.private === true) throw new Error(`${label}: package is marked private`);
  if (manifest.license !== "GPL-3.0-only") {
    throw new Error(`${label}: package license is not GPL-3.0-only`);
  }
  if (manifest.publishConfig?.access !== "public") {
    throw new Error(`${label}: package is not configured for public publication`);
  }
  for (const target of [manifest.main, manifest.module, manifest.types]) {
    if (typeof target !== "string") throw new Error(`${label}: package entry is missing`);
    await stat(join(root, target));
  }
  const files = await walk(root);
  for (const file of files) {
    const relative = file.slice(root.length + 1);
    if (/(^|\/)(src|tests?|fixtures?)(\/|$)|(^|\/)\.env(?:\.|$)/i.test(relative)) {
      throw new Error(`${label}: forbidden package path ${relative}`);
    }
    const value = await readFile(file, "utf8");
    const containsLocalPath = value.includes(sdkRoot) ||
      /(?:\/Users\/|\/home\/|[A-Z]:\\\\Users\\\\)/.test(value);
    if (containsLocalPath || value.includes("workspace:*") || /\.\.\/[^\n\"']*\/src\//.test(value)) {
      throw new Error(`${label}: package contains a repository or source-workspace path`);
    }
    const containsCredential = /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:API_KEY|TOKEN|PASSWORD|SECRET)\s*=\s*[^\s]|\b(?:gh[oprs]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b/.test(value);
    if (containsCredential) {
      throw new Error(`${label}: package contains credential-shaped content`);
    }
  }
}

async function walk(root) {
  const result = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) result.push(...await walk(path));
    else if (entry.isFile()) result.push(path);
  }
  return result;
}

function run(command, args, cwd) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, args, { cwd, env: process.env, stdio: "inherit" });
    child.on("error", rejectRun);
    child.on("exit", (code, signal) => {
      if (code === 0) resolveRun();
      else rejectRun(new Error(`${command} ${args.join(" ")} failed (${signal ?? code})`));
    });
  });
}

function capture(command, args, cwd) {
  return new Promise((resolveCapture, rejectCapture) => {
    let stdout = "";
    let stderr = "";
    const child = spawn(command, args, { cwd, env: process.env });
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", rejectCapture);
    child.on("exit", (code, signal) => {
      if (code === 0) resolveCapture(stdout);
      else rejectCapture(new Error(`${command} failed (${signal ?? code}): ${stderr}`));
    });
  });
}
