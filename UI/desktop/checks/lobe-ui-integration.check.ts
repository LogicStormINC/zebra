import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
const mainSource = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");

assert.equal(packageJson.dependencies["@lobehub/ui"], "5.22.3");
assert.match(import.meta.resolve("@lobehub/ui/es/ThemeProvider/ThemeProvider"), /@lobehub[/+]ui/);
assert.match(mainSource, /import ThemeProvider from "@lobehub\/ui\/es\/ThemeProvider\/ThemeProvider"/);
assert.match(mainSource, /<ThemeProvider\s+appearance="dark"\s+themeMode="dark"/);
assert.doesNotMatch(mainSource, /<ConfigProvider/);

console.log("Lobe UI integration checks passed");
