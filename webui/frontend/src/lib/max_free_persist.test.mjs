import test from 'node:test';
import assert from 'node:assert/strict';
import { fromPreset, mergeSaved, loadMaxFree, saveMaxFree, MAX_FREE_STORAGE_KEY } from './max_free_persist.mjs';

const preset = { enabled_by_default: false, max_free: 1, threshold: 18 };

function mem() {
  const m = new Map();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) };
}

test('i default vengono dal preset', () => {
  const d = fromPreset(preset);
  assert.equal(d.max_free_days, preset.max_free);
  assert.equal(d.full_time_hours, preset.threshold);
  assert.equal(d.max_free_if_full, false);
});

test('la scelta sopravvive al reload', () => {
  const s = mem();
  saveMaxFree({ ...fromPreset(preset), max_free_if_full: true, max_free_days: 2, full_time_hours: 15 }, s);
  const back = loadMaxFree(fromPreset(preset), s);
  assert.equal(back.max_free_if_full, true);
  assert.equal(back.max_free_days, 2);
  assert.equal(back.full_time_hours, 15);
});

test('valori negativi o non interi salvati vengono scartati', () => {
  const out = mergeSaved(fromPreset(preset), { max_free_days: -3, full_time_hours: 'x' });
  assert.equal(out.max_free_days, preset.max_free);
  assert.equal(out.full_time_hours, preset.threshold);
});

test('storage rotto: default', () => {
  const s = { getItem: () => '{rotto', setItem() {} };
  assert.deepEqual(loadMaxFree(fromPreset(preset), s), fromPreset(preset));
  assert.equal(typeof MAX_FREE_STORAGE_KEY, 'string');
});
