import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const sdkRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await mkdtemp(join(tmpdir(), "zebra-react-consumers-"));
const packDirectory = join(workspace, "tarballs");
const keepWorkspace = process.env.ZEBRA_KEEP_CONSUMER_MATRIX === "1";

const packages = {
  "@zebra-agent/contracts": "contracts",
  "@zebra-agent/ui-contracts": "ui-contracts",
  "@zebra-agent/client-core": "client-core",
  "@zebra-agent/react": "react",
};
const reactVersions = [
  {
    label: "react18",
    react: "18.3.1",
    reactTypes: "18.3.31",
    reactDomTypes: "18.3.7",
  },
  {
    label: "react19",
    react: "19.2.8",
    reactTypes: "19.2.18",
    reactDomTypes: "19.2.5",
  },
];

try {
  await mkdir(packDirectory, { recursive: true });
  await run("pnpm", ["build"], sdkRoot);
  const tarballs = await packPackages();

  for (const version of reactVersions) {
    await verifyViteConsumer(version, tarballs);
    await verifyNextConsumer(version, tarballs);
  }

  console.log("\nReact consumer matrix passed: React 18/19 x Vite/Next SSR+RSC");
} finally {
  if (keepWorkspace) {
    console.log(`Consumer matrix workspace retained at ${workspace}`);
  } else {
    await rm(workspace, { force: true, recursive: true });
  }
}

async function packPackages() {
  const tarballs = {};
  for (const [packageName, packageDirectory] of Object.entries(packages)) {
    const before = new Set(await readdir(packDirectory));
    await run(
      "pnpm",
      ["pack", "--pack-destination", packDirectory],
      join(sdkRoot, "packages", packageDirectory),
    );
    const created = (await readdir(packDirectory)).filter(
      (entry) => entry.endsWith(".tgz") && !before.has(entry),
    );
    if (created.length !== 1) {
      throw new Error(`Expected one tarball for ${packageName}, found ${created.length}`);
    }
    tarballs[packageName] = `file:${join(packDirectory, created[0])}`;
  }
  return tarballs;
}

async function verifyViteConsumer(version, tarballs) {
  const consumer = join(workspace, `${version.label}-vite`);
  await writeFiles(consumer, {
    "package.json": JSON.stringify({
      name: `zebra-${version.label}-vite-consumer`,
      private: true,
      type: "module",
      scripts: { build: "tsc --noEmit && vite build" },
      dependencies: consumerDependencies(version, tarballs),
      devDependencies: {
        "@types/react": version.reactTypes,
        "@types/react-dom": version.reactDomTypes,
        typescript: "5.9.3",
        vite: "6.4.3",
      },
      pnpm: { overrides: tarballs },
    }, null, 2),
    "index.html": '<div id="root"></div><script type="module" src="/src/main.ts"></script>',
    "src/main.ts": `
import { createElement, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AgentRunStatus } from "@zebra-agent/react";
import "@zebra-agent/react/styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing root");
createRoot(root).render(createElement(
  StrictMode,
  null,
  createElement(AgentRunStatus, {
    state: { phase: "terminal", outcome: "completed", availableActions: [] },
  }),
));
`,
    "tsconfig.json": JSON.stringify({
      compilerOptions: {
        lib: ["ES2022", "DOM", "DOM.Iterable"],
        module: "ESNext",
        moduleResolution: "Bundler",
        noEmit: true,
        strict: true,
        target: "ES2022",
      },
      include: ["src"],
    }, null, 2),
  });
  await installAndBuild(consumer, `${version.label} / Vite`);
  await verifyTreeShaking(consumer, version.label);
}

async function verifyTreeShaking(consumer, label) {
  const assets = join(consumer, "dist", "assets");
  const scripts = (await readdir(assets)).filter((entry) => entry.endsWith(".js"));
  if (!scripts.length) throw new Error(`${label}: Vite did not emit JavaScript`);
  const output = (await Promise.all(scripts.map((entry) => readFile(join(assets, entry), "utf8")))).join("\n");
  for (const unusedMarker of ["zebra-agent-composer", "Add attachment", "Memory settings"]) {
    if (output.includes(unusedMarker)) {
      throw new Error(`${label}: unused React surface survived tree-shaking: ${unusedMarker}`);
    }
  }
}

async function verifyNextConsumer(version, tarballs) {
  const consumer = join(workspace, `${version.label}-next`);
  await writeFiles(consumer, {
    "package.json": JSON.stringify({
      name: `zebra-${version.label}-next-consumer`,
      private: true,
      scripts: { build: "next build" },
      dependencies: {
        ...consumerDependencies(version, tarballs),
        next: "15.5.18",
      },
      devDependencies: {
        "@types/node": "22.20.4",
        "@types/react": version.reactTypes,
        "@types/react-dom": version.reactDomTypes,
        typescript: "5.9.3",
      },
      pnpm: { overrides: tarballs },
    }, null, 2),
    "app/layout.tsx": `
import type { ReactNode } from "react";
import "@zebra-agent/react/styles.css";

export default function Layout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
`,
    "app/page.tsx": `
import { AgentRunStatus } from "@zebra-agent/react";

export default function RscPage() {
  return <main>
    <h1>RSC consumer</h1>
    <AgentRunStatus state={{ phase: "terminal", outcome: "completed", availableActions: [] }} />
  </main>;
}
`,
    "pages/ssr.tsx": `
import type { GetServerSideProps } from "next";
import { AgentRunStatus } from "@zebra-agent/react";

export default function SsrPage({ label }: { label: string }) {
  return <main>
    <h1>{label}</h1>
    <AgentRunStatus state={{ phase: "terminal", outcome: "completed", availableActions: [] }} />
  </main>;
}

export const getServerSideProps: GetServerSideProps<{ label: string }> = async () => ({
  props: { label: "SSR consumer" },
});
`,
    "tsconfig.json": JSON.stringify({
      compilerOptions: {
        allowJs: false,
        esModuleInterop: true,
        incremental: true,
        jsx: "preserve",
        lib: ["DOM", "DOM.Iterable", "ES2022"],
        module: "ESNext",
        moduleResolution: "Bundler",
        noEmit: true,
        plugins: [{ name: "next" }],
        resolveJsonModule: true,
        strict: true,
        target: "ES2022",
      },
      include: ["next-env.d.ts", ".next/types/**/*.ts", "**/*.ts", "**/*.tsx"],
      exclude: ["node_modules"],
    }, null, 2),
  });
  await installAndBuild(consumer, `${version.label} / Next SSR+RSC`);
}

function consumerDependencies(version, tarballs) {
  return {
    ...tarballs,
    react: version.react,
    "react-dom": version.react,
  };
}

async function installAndBuild(consumer, label) {
  console.log(`\n=== ${label} ===`);
  await run(
    "pnpm",
    ["install", "--ignore-workspace", "--strict-peer-dependencies", "--no-frozen-lockfile"],
    consumer,
  );
  await run("pnpm", ["build"], consumer);
}

async function writeFiles(root, files) {
  for (const [relativePath, contents] of Object.entries(files)) {
    const target = join(root, relativePath);
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, `${contents.trim()}\n`);
  }
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
