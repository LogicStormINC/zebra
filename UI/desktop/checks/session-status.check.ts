import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const statusSource = readFileSync(new URL("../src/_utils/session-status.ts", import.meta.url), "utf8");
const localeSource = readFileSync(new URL("../src/_utils/local.ts", import.meta.url), "utf8");

assert.match(statusSource, /status === "suspended"\) return locale\.statusSuspended/u);
assert.match(localeSource, /statusSuspended: "已暂停"/u);

console.log("session status checks passed");
