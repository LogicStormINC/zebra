import assert from "node:assert/strict";
import { test } from "node:test";
import { validateVegaLiteSpec } from "../src/index.tsx";

const options = { maxInlineDataRows: 2, maxSpecBytes: 4_096, specVersion: "6" };

test("Vega-Lite guard accepts bounded declarative data", () => {
  assert.doesNotThrow(() => validateVegaLiteSpec({ mark: "bar", data: { values: [{ x: "A", y: 1 }] }, encoding: { x: { field: "x" }, y: { field: "y" } } }, options));
});

test("Vega-Lite guard rejects remote and executable content", () => {
  assert.throws(() => validateVegaLiteSpec({ data: { url: "https://evil.example/data.json" }, mark: "bar" }, options), /forbidden/);
  assert.throws(() => validateVegaLiteSpec({ transform: [{ calculate: "datum.secret", as: "x" }], mark: "bar" }, options), /forbidden/);
  assert.throws(() => validateVegaLiteSpec({ transform: [{ filter: "datum.x > 2" }], mark: "bar" }, options), /forbidden/);
  assert.throws(() => validateVegaLiteSpec({ axis: { labelExpr: "datum.label" }, mark: "bar" }, options), /forbidden/);
  assert.throws(() => validateVegaLiteSpec({ condition: { test: "datum.x > 1" }, mark: "bar" }, options), /forbidden/);
});

test("Vega-Lite guard rejects unsupported versions and excessive inline rows", () => {
  assert.throws(() => validateVegaLiteSpec({ mark: "bar" }, { ...options, specVersion: "5" }), /version/);
  assert.throws(() => validateVegaLiteSpec({ data: { values: [1, 2, 3] }, mark: "bar" }, options), /too_large/);
});
