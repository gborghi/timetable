import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_PIPELINE,
  PIPELINE_STORAGE_KEY,
  loadPipeline,
  sanitizePipeline,
  savePipeline,
} from "./pipeline_persist.mjs";

function memStore(seed = {}) {
  const data = { ...seed };
  return {
    getItem(k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
    setItem(k, v) { data[k] = String(v); },
    removeItem(k) { delete data[k]; },
    _data: data,
  };
}

test("sanitizePipeline: empty / junk falls back to defaults", () => {
  assert.deepEqual(sanitizePipeline(null), DEFAULT_PIPELINE);
  assert.deepEqual(sanitizePipeline("nope"), DEFAULT_PIPELINE);
  assert.deepEqual(sanitizePipeline([{ foo: 1 }]), DEFAULT_PIPELINE);
});

test("sanitizePipeline: keeps saved order and toggles", () => {
  const saved = [
    { key: 'phase_b', enabled: false },
    { key: 'phase_a', enabled: true },
    { key: 'hall_check', enabled: false },
  ];
  const out = sanitizePipeline(saved);
  assert.deepEqual(out.slice(0, 3).map((r) => r.key),
    ['phase_b', 'phase_a', 'hall_check']);
  assert.equal(out.find((r) => r.key === 'phase_b').enabled, false);
  assert.equal(out.find((r) => r.key === 'hall_check').enabled, false);
  // New / unsaved default steps are appended, not dropped.
  assert.ok(out.some((r) => r.key === 'rooms'));
  assert.equal(out.length, DEFAULT_PIPELINE.length);
});

test("sanitizePipeline: drops unknown keys and duplicates", () => {
  const out = sanitizePipeline([
    { key: 'phase_a', enabled: true },
    { key: 'not_a_step', enabled: true },
    { key: 'phase_a', enabled: false },
  ]);
  assert.equal(out.filter((r) => r.key === 'phase_a').length, 1);
  assert.ok(!out.some((r) => r.key === 'not_a_step'));
});

test("load/save round-trip through a Storage stand-in", () => {
  const store = memStore();
  const next = sanitizePipeline([
    { key: 'rooms', enabled: true },
    { key: 'phase_a', enabled: false },
  ]);
  savePipeline(next, store);
  assert.ok(store.getItem(PIPELINE_STORAGE_KEY));
  const loaded = loadPipeline(store);
  assert.equal(loaded[0].key, 'rooms');
  assert.equal(loaded[0].enabled, true);
  assert.equal(loaded.find((r) => r.key === 'phase_a').enabled, false);
});

test("loadPipeline: missing or corrupt storage returns defaults", () => {
  assert.deepEqual(loadPipeline(memStore()), DEFAULT_PIPELINE);
  assert.deepEqual(
    loadPipeline(memStore({ [PIPELINE_STORAGE_KEY]: '{not json' })),
    DEFAULT_PIPELINE,
  );
});
